import hashlib
import json
import time

from . import db
from .redis_client import r

STREAM = "jobs"
GROUP = "workers"
DELAYED = "jobs:delayed"
PRIORITY = "jobs:priority"
DEAD = "dead"
QUEUED_PREFIX = "queued:"

PRIORITY_HIGH = 10
PRIORITY_DEFAULT = 50
PRIORITY_LOW = 90


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def ensure_group() -> None:
    try:
        r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def is_recently_scraped(url: str, max_age_seconds: int = 604800) -> bool:
    digest = url_hash(url)
    if r.exists(f"scraped:{digest}"):
        return True
    try:
        row = db.query_one(
            """
            SELECT 1 FROM crawl_url
            WHERE url_hash = %s AND status = 'done'
            AND last_fetched_at > now() - (%s || ' seconds')::interval
            LIMIT 1
            """,
            (digest, str(max_age_seconds)),
        )
        return row is not None
    except Exception:
        return False


def mark_scraped(url: str, max_age_seconds: int = 604800) -> None:
    r.setex(f"scraped:{url_hash(url)}", max_age_seconds, "1")


def enqueue(url: str, kind: str, priority: int = 0, next_run_at: float | None = None, extra: dict | None = None) -> bool:
    extra = extra or {}
    payload = {"url": url, "kind": kind, "priority": int(priority), **extra}
    digest = url_hash(url)

    if kind == "profile" and is_recently_scraped(url):
        return False

    if next_run_at and next_run_at > time.time():
        r.zadd(DELAYED, {json.dumps(payload, sort_keys=True): next_run_at})
        return False

    if not r.set(f"{QUEUED_PREFIX}{digest}", "1", nx=True, ex=86400):
        return False

    score = int(priority) * 1_000_000_000 + int(time.time())
    r.zadd(PRIORITY, {json.dumps(payload, sort_keys=True): score})

    try:
        db.execute(
            """
            INSERT INTO crawl_url (url_hash, url, kind, priority, status, next_run_at, updated_at)
            VALUES (%s, %s, %s, %s, 'queued', now(), now())
            ON CONFLICT (url_hash) DO UPDATE
            SET status = 'queued', updated_at = now()
            """,
            (digest, url, kind, int(priority)),
        )
    except Exception:
        pass
    return True


def claim_job(count: int = 1) -> list[tuple[str, dict]]:
    entries = []
    for _ in range(count):
        result = r.zpopmin(PRIORITY, count=1)
        if not result:
            break
        raw, _score = result[0]
        try:
            payload = json.loads(raw)
            msg_id = r.xadd(STREAM, {key: str(value) for key, value in payload.items()})
            entries.append((msg_id, payload))
        except Exception:
            pass
    return entries


def move_due(limit: int = 100) -> int:
    moved = 0
    now = time.time()
    for raw in r.zrangebyscore(DELAYED, "-inf", now, start=0, num=limit):
        try:
            payload = json.loads(raw)
            digest = url_hash(payload["url"])
            if not r.set(f"{QUEUED_PREFIX}{digest}", "1", nx=True, ex=86400):
                r.zrem(DELAYED, raw)
                continue
            score = int(payload.get("priority", 0)) * 1_000_000_000 + int(time.time())
            r.zadd(PRIORITY, {raw: score})
            r.zrem(DELAYED, raw)
            moved += 1
        except Exception:
            r.zrem(DELAYED, raw)
    return moved


def ack(msg_id: str, url: str) -> None:
    r.xack(STREAM, GROUP, msg_id)
    r.xdel(STREAM, msg_id)
    r.delete(f"{QUEUED_PREFIX}{url_hash(url)}")


def retry_later(url: str, kind: str, delay: float, priority: int = 0, extra: dict | None = None) -> None:
    r.delete(f"{QUEUED_PREFIX}{url_hash(url)}")
    payload = {"url": url, "kind": kind, "priority": int(priority), **(extra or {})}
    r.zadd(DELAYED, {json.dumps(payload, sort_keys=True): time.time() + delay})


def dead(job: dict, error: Exception | str, attempts: int) -> None:
    url = job.get("url", "")
    kind = job.get("kind", "")
    r.xadd(
        DEAD,
        {"url": url, "kind": kind, "error": str(error)[:1000], "attempts": str(attempts)},
    )
    r.delete(f"{QUEUED_PREFIX}{url_hash(url)}")
    try:
        db.execute(
            "INSERT INTO dead_letter (url, kind, error, attempts) VALUES (%s, %s, %s, %s)",
            (url, kind, str(error)[:2000], attempts),
        )
        db.execute(
            "UPDATE crawl_url SET status = 'failed', attempts = %s, updated_at = now() WHERE url_hash = %s",
            (attempts, url_hash(url)),
        )
    except Exception:
        pass


def requeue_stale(min_idle_ms: int = 600000, count: int = 100) -> int:
    requeued = 0
    try:
        result = r.xautoclaim(
            STREAM,
            GROUP,
            "maintenance",
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=count,
        )
        entries = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else []
        for msg_id, fields in entries:
            r.xack(STREAM, GROUP, msg_id)
            r.xdel(STREAM, msg_id)
            r.delete(f"{QUEUED_PREFIX}{url_hash(fields.get('url', ''))}")
            extra = {
                key: value
                for key, value in fields.items()
                if key not in {"url", "kind", "priority"}
            }
            if enqueue(
                fields["url"],
                fields.get("kind", "listing"),
                int(fields.get("priority", 0) or 0),
                extra=extra,
            ):
                requeued += 1
    except Exception:
        pass
    return requeued


def retry_dead(limit: int = 100) -> int:
    requeued = 0
    for msg_id, fields in r.xrange(DEAD, "-", "+", count=limit):
        if enqueue(fields.get("url", ""), fields.get("kind", "listing")):
            r.xdel(DEAD, msg_id)
            requeued += 1
    return requeued


def queue_stats() -> dict:
    try:
        pending = r.xpending(STREAM, GROUP) or {}
    except Exception:
        pending = {}
    return {
        "pending": int(pending.get("pending", 0) or 0),
        "consumers": len(pending.get("consumers", []) or []),
        "priority": int(r.zcard(PRIORITY)),
        "delayed": int(r.zcard(DELAYED)),
        "dead": int(r.xlen(DEAD)),
        "stream": int(r.xlen(STREAM)),
    }


def list_pending(limit: int = 50) -> list[dict]:
    return [{"id": msg_id, **fields} for msg_id, fields in r.xrange(STREAM, "-", "+", count=limit)]


def list_active(limit: int = 50) -> list[dict]:
    try:
        items = r.xpending_range(STREAM, GROUP, "-", "+", count=limit)
    except Exception:
        return []
    active = []
    for item in items:
        msg_id = item["message_id"]
        entries = r.xrange(STREAM, msg_id, msg_id)
        if entries:
            _, fields = entries[0]
            active.append(
                {
                    "id": msg_id,
                    "idle_ms": item.get("idle", 0),
                    "consumer": item.get("consumer"),
                    "deliveries": item.get("times_delivered"),
                    **fields,
                }
            )
    return active


def list_dead(limit: int = 50) -> list[dict]:
    return [{"id": msg_id, **fields} for msg_id, fields in r.xrange(DEAD, "-", "+", count=limit)]


def purge() -> None:
    r.delete(STREAM, DELAYED, PRIORITY, DEAD)
    for key in r.scan_iter(f"{QUEUED_PREFIX}*"):
        r.delete(key)
    ensure_group()
    try:
        db.execute("UPDATE crawl_url SET status = 'queued', updated_at = now() WHERE status = 'failed'")
    except Exception:
        pass
