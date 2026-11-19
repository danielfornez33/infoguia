import time
from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=12,
            open=True,
            timeout=30,
        )
    return _pool


def init_db(retries: int = 40, delay: float = 2.0) -> None:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with pool().connection() as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'company')"
                    )
                    result = cur.fetchone()
                    if result and result[0]:
                        return
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_try_advisory_lock(918273645)")
                    result = cur.fetchone()
                    if not result or not result[0]:
                        time.sleep(delay)
                        continue
                    try:
                        cur.execute(SCHEMA)
                    finally:
                        try:
                            cur.execute("SELECT pg_advisory_unlock(918273645)")
                        except Exception:
                            pass
                    conn.commit()
                return
        except Exception as exc:
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"no se pudo inicializar la base de datos: {last_error}")


@contextmanager
def cursor():
    with pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur
        conn.commit()


def query(sql: str, params=None) -> list[dict]:
    with pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def query_one(sql: str, params=None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=None) -> None:
    with pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
        conn.commit()
