import time

from .redis_client import r
from .settings_store import get_bool, get_float, get_int

TOKEN_BUCKET = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = burst end
if ts == nil then ts = now end
tokens = math.min(burst, tokens + (now - ts) * rate)
if tokens < 1 then
  local wait = (1 - tokens) / rate
  redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
  return wait
end
tokens = tokens - 1
redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
return 0
"""

_LATENCY_WINDOW = "rl:latency"
_LATENCY_TTL = 300


def wait_for_slot(host: str) -> float:
    rate = max(get_effective_rate(host), 0.001)
    burst = max(get_int("crawl_burst", 1), 1)
    total_wait = 0.0
    while True:
        wait = float(r.eval(TOKEN_BUCKET, 1, f"rl:{host}", rate, burst, time.time()))
        if wait <= 0:
            return total_wait
        total_wait += min(wait, 30.0)
        time.sleep(min(wait, 30.0))


def report_latency(host: str, latency_seconds: float) -> None:
    now = time.time()
    r.zadd(_LATENCY_WINDOW, {f"{host}:{now}": now})
    r.zremrangebyscore(_LATENCY_WINDOW, "-inf", now - _LATENCY_TTL)
    host_key = f"rl:latency:{host}"
    r.hset(host_key, mapping={
        str(now): str(latency_seconds),
    })
    cutoff = now - _LATENCY_TTL
    existing = r.hkeys(host_key)
    for key in existing:
        try:
            if float(key) < cutoff:
                r.hdel(host_key, key)
        except (ValueError, TypeError):
            pass


def get_effective_rate(host: str) -> float:
    base_rate = max(get_float("crawl_rps", 0.15), 0.001)
    key = f"rl:latency:{host}"
    entries = r.hvals(key)
    if not entries:
        return base_rate
    latencies = [float(v) for v in entries]
    recent = latencies[-10:]
    avg_latency = sum(recent) / len(recent)
    if avg_latency < 2.0:
        factor = 1.0
    elif avg_latency < 5.0:
        factor = 0.7
    elif avg_latency < 10.0:
        factor = 0.4
    else:
        factor = 0.2
    return base_rate * factor


def daily_key() -> str:
    return "counter:" + time.strftime("%Y-%m-%d")


def daily_count() -> int:
    value = r.get(daily_key())
    return int(value or 0)


def daily_allowed() -> bool:
    cap = get_int("daily_cap", 8000)
    if cap <= 0:
        return True
    return daily_count() < cap


def consume_daily() -> bool:
    cap = get_int("daily_cap", 8000)
    if cap <= 0:
        return True
    key = daily_key()
    count = r.incr(key)
    if count == 1:
        r.expire(key, 172800)
    return count <= cap


def in_off_peak() -> bool:
    if not get_bool("off_peak_only", False):
        return True
    start = get_int("off_peak_start", 0)
    end = get_int("off_peak_end", 7)
    if start == end:
        return True
    hour = time.localtime().tm_hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end
