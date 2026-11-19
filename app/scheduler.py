import time
from pathlib import Path

from . import db, queue
from .config import settings
from .events import error as log_error
from .events import info as log_info
from .ratelimit import in_off_peak
from .redis_client import r
from .settings_store import load_settings


def seed_defaults() -> None:
    row = db.query_one("SELECT count(*) AS total FROM seed")
    if row and row["total"]:
        return
    urls = list(settings.seeds)
    path = Path("seeds.txt")
    if path.exists():
        urls.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    for url in dict.fromkeys(urls):
        db.execute(
            """
            INSERT INTO seed (url, kind, interval_seconds, enabled, next_run_at)
            VALUES (%s, 'listing', 86400, true, now())
            ON CONFLICT (url) DO NOTHING
            """,
            (url,),
        )


def mode() -> str:
    return r.get("control:mode") or "running"


def scheduler_heartbeat(status: str = "running") -> None:
    now = time.time()
    r.set("scheduler:hb", now, ex=30)
    r.hset(
        "scheduler:status",
        mapping={
            "last_seen": now,
            "status": status,
            "off_peak": str(not in_off_peak()),
        },
    )


def scheduler_is_alive(max_age_seconds: float = 60.0) -> bool:
    hb = r.get("scheduler:hb")
    if hb is None:
        return False
    try:
        return (time.time() - float(hb)) < max_age_seconds
    except (ValueError, TypeError):
        return False


def main() -> None:
    db.init_db()
    queue.ensure_group()
    load_settings()
    seed_defaults()
    log_info("scheduler iniciado")

    last_heartbeat = 0.0
    last_stale = 0.0
    while True:
        try:
            current_status = "running"
            if mode() in {"running", "paused"}:
                if in_off_peak():
                    queue.move_due()

                    if mode() == "running":
                        rows = db.query(
                            """
                            SELECT * FROM seed
                            WHERE enabled = true AND next_run_at <= now()
                            ORDER BY next_run_at ASC
                            LIMIT 20
                            """
                        )
                        for row in rows:
                            if queue.enqueue(row["url"], row["kind"], priority=queue.PRIORITY_DEFAULT):
                                db.execute(
                                    "UPDATE seed SET next_run_at = now() + make_interval(secs => %s) WHERE id = %s",
                                    (row["interval_seconds"], row["id"]),
                                )
                                log_info("seed encolada", url=row["url"], kind=row["kind"])

                    if time.time() - last_stale > 60:
                        requeued = queue.requeue_stale()
                        if requeued:
                            log_info("jobs reencolados", count=requeued)
                        last_stale = time.time()
                else:
                    current_status = "off-peak"
            else:
                current_status = mode()

            if time.time() - last_heartbeat > 10:
                scheduler_heartbeat(current_status)
                last_heartbeat = time.time()
        except Exception as exc:
            log_error("scheduler error", error=str(exc))
            scheduler_heartbeat("error")
        time.sleep(10)


if __name__ == "__main__":
    main()
