import redis
import redis.asyncio as aredis

from .config import settings

r = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_timeout=30,
    socket_connect_timeout=10,
    health_check_interval=30,
)
ar = aredis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_timeout=30,
    socket_connect_timeout=10,
    health_check_interval=30,
)


def ping() -> bool:
    return bool(r.ping())
