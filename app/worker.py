import gzip
import hashlib
import json
import os
import signal
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import redis

from . import db, queue
from .adapters import get_adapter_for_url
from .anomaly import analyze_response
from .config import settings
from .events import error as log_error
from .events import info as log_info
from .events import warn as log_warn
from .ratelimit import consume_daily, daily_allowed, in_off_peak, report_latency, wait_for_slot
from .redis_client import r
from .robots import can_fetch
from .rotation import build_browser_headers, get_proxy_rotator, get_ua_rotator
from .settings_store import get_bool, get_int, load_settings
from .upsert import (
    save_snapshot,
    upsert_branch,
    upsert_category,
    upsert_company,
    upsert_company_category,
    upsert_contact,
    upsert_product,
    upsert_social,
)

HOSTNAME = socket.gethostname()
WORKER_ID = f"{HOSTNAME}-{os.getpid()}"
STOP = False
PROCESSED = 0
ERRORS = 0


def _build_client() -> httpx.Client:
    headers: dict[str, str] = {}
    if not settings.rotate_user_agents:
        headers["User-Agent"] = settings.crawl_user_agent
    return httpx.Client(
        headers=headers or None,
        timeout=settings.http_timeout,
        follow_redirects=True,
    )


CLIENT = _build_client()


def handle_signal(signum, frame):
    global STOP
    STOP = True


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def mode() -> str:
    return r.get("control:mode") or "running"


def wait_control() -> None:
    while not STOP:
        current = mode()
        if current == "running":
            return
        if current == "stopping":
            raise SystemExit(0)
        time.sleep(2)
    raise SystemExit(0)


def heartbeat(status: str = "running") -> None:
    now = time.time()
    r.set(f"worker:hb:{WORKER_ID}", now, ex=30)
    r.hset(
        "workers",
        WORKER_ID,
        json.dumps(
            {
                "last_seen": now,
                "status": status,
                "processed": PROCESSED,
                "errors": ERRORS,
                "hostname": HOSTNAME,
                "pid": os.getpid(),
            }
        ),
    )
    try:
        db.execute(
            """
            INSERT INTO worker (id, hostname, pid, started_at, last_seen, processed, errors)
            VALUES (%s, %s, %s, now(), now(), %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET last_seen = now(), processed = EXCLUDED.processed, errors = EXCLUDED.errors
            """,
            (WORKER_ID, HOSTNAME, os.getpid(), PROCESSED, ERRORS),
        )
    except Exception:
        pass


def save_raw(content: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(content).hexdigest()
    now = datetime.now(UTC)
    path = Path(settings.raw_dir) / now.strftime("%Y/%m/%d") / f"{digest}.html.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with gzip.open(path, "wb") as handle:
            handle.write(content)
    return str(path), digest


class BlockedError(Exception):
    pass


class CaptchaError(Exception):
    pass


class StructureChangedError(Exception):
    pass


def _get_cached_headers(url: str) -> dict[str, str]:
    if not settings.conditional_requests:
        return {}
    key = f"http_cache:{queue.url_hash(url)}"
    cached = r.hgetall(key)
    headers: dict[str, str] = {}
    if cached:
        etag = cached.get(b"etag") or cached.get("etag")
        last_modified = cached.get(b"last_modified") or cached.get("last_modified")
        if etag:
            headers["If-None-Match"] = etag.decode() if isinstance(etag, bytes) else etag
        if last_modified:
            headers["If-Modified-Since"] = (
                last_modified.decode() if isinstance(last_modified, bytes) else last_modified
            )
    return headers


def _save_cached_headers(url: str, response_headers: dict) -> None:
    if not settings.conditional_requests:
        return
    key = f"http_cache:{queue.url_hash(url)}"
    data: dict[str, str] = {}
    etag = response_headers.get("etag")
    last_modified = response_headers.get("last-modified")
    if etag:
        data["etag"] = etag
    if last_modified:
        data["last_modified"] = last_modified
    if data:
        r.hset(key, mapping=data)
        r.expire(key, 86400 * 7)


def _build_fingerprinted_headers(url: str) -> dict[str, str]:
    ua = get_ua_rotator().get_user_agent() if settings.rotate_user_agents else None
    headers = build_browser_headers(user_agent=ua)
    headers.update(_get_cached_headers(url))
    return headers


def _get_proxy() -> str | None:
    if not settings.proxy_rotation_enabled:
        return None
    rotator = get_proxy_rotator(settings.proxies or None)
    return rotator.get_proxy()


def fetch(url: str) -> httpx.Response:
    proxy = _get_proxy()
    request_headers = _build_fingerprinted_headers(url)

    client = CLIENT
    transport = None
    if proxy:
        transport = httpx.HTTPTransport(proxy=proxy)
        client = httpx.Client(
            headers=request_headers,
            timeout=settings.http_timeout,
            follow_redirects=True,
            transport=transport,
        )
    else:
        client.headers.update(request_headers)

    try:
        response = client.get(url)
    except Exception:
        if proxy:
            get_proxy_rotator().report_failure(proxy)
        raise
    finally:
        if proxy and transport:
            client.close()

    if proxy:
        if response.status_code < 400:
            get_proxy_rotator().report_success(proxy)
        else:
            get_proxy_rotator().report_failure(proxy)

    if response.status_code == 304:
        return response

    if response.status_code in (403, 429):
        host = urlparse(url).netloc
        r.setex(f"blocked:{host}", 3600, "1")
        raise BlockedError(f"HTTP {response.status_code}")
    if response.status_code in (500, 502, 503, 504):
        raise RuntimeError(f"HTTP {response.status_code}")
    response.raise_for_status()

    _save_cached_headers(url, response.headers)

    adapter = get_adapter_for_url(url)
    kind = adapter.detect_kind(url)
    anomaly = analyze_response(response.text, kind)
    if anomaly.captcha_detected:
        raise CaptchaError(f"CAPTCHA detected: {anomaly.captcha_type}")
    if anomaly.structure_changed:
        raise StructureChangedError(anomaly.reason)

    return response


def mark_done(url: str) -> None:
    db.execute(
        """
        UPDATE crawl_url
        SET status = 'done', last_fetched_at = now(), updated_at = now(), attempts = 0
        WHERE url_hash = %s
        """,
        (queue.url_hash(url),),
    )


_KIND_PRIORITY = {
    "profile": queue.PRIORITY_HIGH,
    "listing": queue.PRIORITY_DEFAULT,
    "store": queue.PRIORITY_LOW,
}


def enqueue_all(items: list[tuple[str, str, dict]]) -> int:
    count = 0
    for url, kind, extra in items:
        if not url:
            continue
        priority = _KIND_PRIORITY.get(kind, queue.PRIORITY_DEFAULT)
        if queue.enqueue(url, kind, priority=priority, extra=extra):
            count += 1
    return count


def handle_listing(response: httpx.Response, url: str, sha: str, raw_path: str) -> list[tuple[str, str, dict]]:
    adapter = get_adapter_for_url(url)
    data = adapter.parse_listing(response.text, url)
    pending: list[tuple[str, str, dict]] = []
    products_enabled = get_bool("products_enabled", True)
    discovery_enabled = get_bool("discovery_enabled", False)
    max_pages = get_int("max_pages_per_listing", 30)

    with db.cursor() as cur:
        for category in data["categories"]:
            upsert_category(cur, category["cat_id"], category["name"])

        for company in data["companies"]:
            clte = int(company["clte"])
            upsert_company(
                cur,
                {
                    "clte": clte,
                    "name": company["name"],
                    "verified": company["verified"],
                    "description": company["description"],
                    "rating_pct": company["rating_pct"],
                    "store_url": company["store_url"] or None,
                    "profile_url": company["profile_url"],
                    "content_sha": sha,
                },
            )
            upsert_branch(
                cur,
                clte,
                {
                    "branch_key": "0",
                    "urbanization": "",
                    "address": company["address"],
                    "city": company["city"],
                    "phones": " ".join(company["phones"]),
                    "whatsapp": " ".join(company["whatsapp"]),
                    "email": "",
                },
            )
            for contact in company["contacts"]:
                upsert_contact(cur, clte, "0", contact["type"], contact["value"])
            if company["cat_id"]:
                upsert_company_category(cur, clte, company["cat_id"])
            pending.append((company["profile_url"], "profile", {"clte": clte}))
            if products_enabled and company["store_url"]:
                pending.append((company["store_url"], "store", {"clte": clte}))

        save_snapshot(
            cur,
            url,
            queue.url_hash(url),
            "listing",
            response.status_code,
            response.headers,
            sha,
            raw_path,
        )

    for page in data["next_pages"][:max_pages]:
        pending.append((page, "listing", {}))

    if discovery_enabled:
        for discovered in data["discovered"][:100]:
            if "cat=" in discovered and "ciud=" in discovered:
                pending.append((discovered, "listing", {}))

    return pending


def handle_profile(response: httpx.Response, url: str, sha: str, raw_path: str, fields: dict) -> list[tuple[str, str, dict]]:
    adapter = get_adapter_for_url(url)
    data = adapter.parse_profile(response.text, url)
    clte = fields.get("clte")
    if not clte:
        row = db.query_one("SELECT clte FROM company WHERE source_url = %s LIMIT 1", (url,))
        clte = row["clte"] if row else None
    if not clte:
        raise RuntimeError("no se pudo identificar clte del perfil")
    clte = int(clte)

    pending: list[tuple[str, str, dict]] = []
    with db.cursor() as cur:
        upsert_company(
            cur,
            {
                "clte": clte,
                "name": data["name"],
                "verified": data["verified"],
                "description": data["description"] or None,
                "rating_pct": data["rating_pct"],
                "store_url": data["store_url"] or None,
                "profile_url": url,
                "content_sha": sha,
            },
        )
        for branch in data["branches"]:
            upsert_branch(cur, clte, branch)
            for contact in branch["contacts"]:
                upsert_contact(cur, clte, branch["branch_key"], contact["type"], contact["value"])
        for social in data["socials"]:
            upsert_social(cur, clte, social["network"], social["url"])
        for category in data["categories"]:
            upsert_category(cur, category["cat_id"], category["name"])
            upsert_company_category(cur, clte, category["cat_id"])
        for product in data["products"]:
            upsert_product(cur, clte, product)
        save_snapshot(
            cur,
            url,
            queue.url_hash(url),
            "profile",
            response.status_code,
            response.headers,
            sha,
            raw_path,
        )

    if get_bool("products_enabled", True) and data["store_url"]:
        pending.append((data["store_url"], "store", {"clte": clte}))
    return pending


def handle_store(response: httpx.Response, url: str, sha: str, raw_path: str, fields: dict) -> list[tuple[str, str, dict]]:
    adapter = get_adapter_for_url(url)
    data = adapter.parse_store(response.text, url)
    clte = fields.get("clte")
    if not clte:
        row = db.query_one("SELECT clte FROM company WHERE store_url = %s LIMIT 1", (url,))
        clte = row["clte"] if row else None
    if not clte:
        raise RuntimeError("no se pudo identificar clte de la tienda")
    clte = int(clte)

    with db.cursor() as cur:
        for product in data["products"]:
            upsert_product(cur, clte, product)
        save_snapshot(
            cur,
            url,
            queue.url_hash(url),
            "store",
            response.status_code,
            response.headers,
            sha,
            raw_path,
        )
    return []


def process(msg_id: str, fields: dict) -> None:
    global PROCESSED, ERRORS
    url = fields.get("url") or ""
    kind = fields.get("kind") or "listing"
    attempts = int(float(fields.get("attempts") or 0))
    if not url:
        queue.ack(msg_id, url)
        return

    if not can_fetch(url):
        log_warn("robots disallow", url=url, worker=WORKER_ID)
        queue.ack(msg_id, url)
        return

    host = urlparse(url).netloc
    if r.exists(f"blocked:{host}"):
        log_warn("host bloqueado temporalmente", url=url, worker=WORKER_ID)
        queue.retry_later(url, kind, 1800, extra={"attempts": attempts})
        queue.ack(msg_id, url)
        return

    if not consume_daily():
        log_warn("tope diario alcanzado, reprogramando", url=url, worker=WORKER_ID)
        queue.retry_later(url, kind, 3600, extra={"attempts": attempts})
        queue.ack(msg_id, url)
        return

    try:
        wait_for_slot(urlparse(url).netloc)
        started = time.time()
        response = fetch(url)
        latency = time.time() - started
        report_latency(urlparse(url).netloc, latency)

        if response.status_code == 304:
            mark_done(url)
            queue.mark_scraped(url)
            queue.ack(msg_id, url)
            PROCESSED += 1
            log_info(
                "not modified",
                url=url,
                kind=kind,
                status=304,
                worker=WORKER_ID,
            )
            return

        raw_path, sha = save_raw(response.content)

        if kind == "listing":
            pending = handle_listing(response, url, sha, raw_path)
        elif kind == "profile":
            pending = handle_profile(response, url, sha, raw_path, fields)
        elif kind == "store":
            pending = handle_store(response, url, sha, raw_path, fields)
        else:
            raise RuntimeError(f"tipo de job desconocido: {kind}")

        enqueued = enqueue_all(pending)
        mark_done(url)
        queue.mark_scraped(url)
        queue.ack(msg_id, url)
        PROCESSED += 1
        log_info(
            "ok",
            url=url,
            kind=kind,
            status=response.status_code,
            bytes=len(response.content),
            enqueued=enqueued,
            worker=WORKER_ID,
        )
    except BlockedError as exc:
        log_warn("bloqueo del sitio, enfriando 1 h", url=url, error=str(exc), worker=WORKER_ID)
        extra = {"attempts": attempts}
        if fields.get("clte"):
            extra["clte"] = fields["clte"]
        queue.retry_later(url, kind, 3600, extra=extra)
        queue.ack(msg_id, url)
    except CaptchaError as exc:
        log_warn("captcha detectado, enfriando 2 h", url=url, error=str(exc), worker=WORKER_ID)
        extra = {"attempts": attempts}
        if fields.get("clte"):
            extra["clte"] = fields["clte"]
        queue.retry_later(url, kind, 7200, extra=extra)
        host = urlparse(url).netloc
        r.setex(f"blocked:{host}", 7200, "captcha")
        queue.ack(msg_id, url)
    except StructureChangedError as exc:
        log_warn("estructura de página cambió", url=url, error=str(exc), worker=WORKER_ID)
        r.setex(f"structure_changed:{urlparse(url).netloc}", 86400, str(exc)[:200])
        extra = {"attempts": attempts}
        if fields.get("clte"):
            extra["clte"] = fields["clte"]
        queue.retry_later(url, kind, 86400, extra=extra)
        queue.ack(msg_id, url)
    except Exception as exc:
        ERRORS += 1
        attempts += 1
        log_error("fallo", url=url, kind=kind, error=str(exc), attempts=attempts, worker=WORKER_ID)
        if attempts < settings.max_retries:
            extra = {"attempts": attempts}
            if fields.get("clte"):
                extra["clte"] = fields["clte"]
            queue.retry_later(url, kind, 60 * (2 ** attempts), extra=extra)
        else:
            queue.dead({"url": url, "kind": kind}, exc, attempts)
        queue.ack(msg_id, url)


def main() -> None:
    db.init_db()
    queue.ensure_group()
    load_settings()
    heartbeat("starting")
    log_info("worker iniciado", worker=WORKER_ID)

    last_heartbeat = 0.0
    while not STOP:
        wait_control()

        if not in_off_peak():
            if time.time() - last_heartbeat > 10:
                heartbeat("off-peak")
                last_heartbeat = time.time()
            time.sleep(30)
            continue

        if not daily_allowed():
            if time.time() - last_heartbeat > 10:
                heartbeat("daily-cap")
                last_heartbeat = time.time()
            time.sleep(300)
            continue

        try:
            queue.move_due()
            queue.claim_job(count=5)
            messages = r.xreadgroup(
                queue.GROUP,
                WORKER_ID,
                {queue.STREAM: ">"},
                count=1,
                block=5000,
            )
        except redis.exceptions.TimeoutError:
            continue
        except redis.exceptions.RedisError as exc:
            log_error("redis error", error=str(exc), worker=WORKER_ID)
            time.sleep(2)
            continue

        if not messages:
            if time.time() - last_heartbeat > 10:
                heartbeat("idle")
                last_heartbeat = time.time()
            continue

        _, entries = messages[0]
        for msg_id, fields in entries:
            wait_control()
            try:
                process(msg_id, fields)
            except Exception as exc:
                log_error("proceso inesperado", url=fields.get("url"), error=str(exc), worker=WORKER_ID)
                queue.ack(msg_id, fields.get("url", ""))
            heartbeat("running")
            last_heartbeat = time.time()

    log_info("worker detenido", worker=WORKER_ID, processed=PROCESSED, errors=ERRORS)


if __name__ == "__main__":
    main()
