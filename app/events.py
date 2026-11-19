import json
from datetime import UTC, datetime

from .redis_client import r


def emit(level: str, message: str, **fields) -> None:
    event = {
        "ts": datetime.now(UTC).isoformat(),
        "level": level.upper(),
        "message": message,
        **fields,
    }
    line = json.dumps(event, ensure_ascii=False, default=str)
    print(line, flush=True)
    try:
        r.publish("events", line)
        r.lpush("logs:recent", line)
        r.ltrim("logs:recent", 0, 499)
    except Exception:
        pass


def info(message: str, **fields) -> None:
    emit("INFO", message, **fields)


def warn(message: str, **fields) -> None:
    emit("WARN", message, **fields)


def error(message: str, **fields) -> None:
    emit("ERROR", message, **fields)
