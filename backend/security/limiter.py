"""Shared Redis fixed-window limits with a bounded local fallback."""
from collections import defaultdict
import os
from threading import Lock
import time

_lock = Lock()
_local = defaultdict(lambda: [0, 0.0])
_redis = None
_redis_failed_at = 0.0

_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {count, redis.call('TTL', KEYS[1])}
"""


def _client():
    global _redis, _redis_failed_at
    url = os.getenv('REDIS_URL', '').strip()
    if not url or time.monotonic() - _redis_failed_at < 30:
        return None
    if _redis is None:
        try:
            import redis
            _redis = redis.Redis.from_url(url, socket_connect_timeout=1,
                                          socket_timeout=1, decode_responses=True)
            _redis.ping()
        except Exception:
            _redis = None
            _redis_failed_at = time.monotonic()
    return _redis


def hit(scope, identity, limit, seconds):
    """Return (allowed, retry_after, backend). Never include raw secrets in keys."""
    key = 'amt:limit:' + scope + ':' + identity
    client = _client()
    if client is not None:
        try:
            count, ttl = client.eval(_SCRIPT, 1, key, seconds)
            return int(count) <= limit, max(1, int(ttl)), 'redis'
        except Exception:
            global _redis, _redis_failed_at
            _redis = None
            _redis_failed_at = time.monotonic()
    now = time.monotonic()
    with _lock:
        count, expires = _local[key]
        if expires <= now:
            count, expires = 0, now + seconds
        count += 1
        _local[key] = [count, expires]
        # Prevent unbounded attacker-controlled identities in the fallback.
        if len(_local) > 10_000:
            for old_key in list(_local)[:2_000]:
                if _local[old_key][1] <= now:
                    _local.pop(old_key, None)
    return count <= limit, max(1, int(expires - now)), 'memory'
