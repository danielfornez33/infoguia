from .config import settings
from .db import cursor, query
from .redis_client import r

DEFAULTS = {
    "crawl_rps": str(settings.crawl_rps),
    "crawl_burst": str(settings.crawl_burst),
    "daily_cap": str(settings.daily_cap),
    "off_peak_only": "true" if settings.off_peak_only else "false",
    "off_peak_start": str(settings.off_peak_start),
    "off_peak_end": str(settings.off_peak_end),
    "discovery_enabled": "true" if settings.discovery_enabled else "false",
    "products_enabled": "true" if settings.products_enabled else "false",
    "max_pages_per_listing": str(settings.max_pages_per_listing),
}


def load_settings() -> None:
    rows = query("SELECT key, value FROM setting")
    stored = {row["key"]: row["value"] for row in rows}
    merged = {**DEFAULTS, **stored}
    r.hset("settings", mapping=merged)


def get_setting(key: str, default: str | None = None) -> str | None:
    value = r.hget("settings", key)
    if value is None:
        value = DEFAULTS.get(key, default)
        if value is not None:
            r.hset("settings", key, value)
    return value


def get_float(key: str, default: float) -> float:
    try:
        return float(get_setting(key, str(default)))
    except (TypeError, ValueError):
        return default


def get_int(key: str, default: int) -> int:
    try:
        return int(float(get_setting(key, str(default))))
    except (TypeError, ValueError):
        return default


def get_bool(key: str, default: bool) -> bool:
    value = get_setting(key, "true" if default else "false")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def all_settings() -> dict[str, str]:
    stored = r.hgetall("settings")
    return {**DEFAULTS, **stored}


def set_settings(values: dict[str, object]) -> dict[str, str]:
    mapping = {key: str(value) for key, value in values.items() if value is not None}
    if not mapping:
        return all_settings()
    r.hset("settings", mapping=mapping)
    with cursor() as cur:
        for key, value in mapping.items():
            cur.execute(
                """
                INSERT INTO setting (key, value, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = now()
                """,
                (key, value),
            )
    return all_settings()
