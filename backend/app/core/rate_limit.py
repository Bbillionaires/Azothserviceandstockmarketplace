"""Rate limiting.

With ``REDIS_URL`` set, counters live in Redis (fixed windows) so limits hold
across API replicas. Otherwise an in-process sliding window is used, which is
fine for a single instance and for tests.
"""

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again shortly.")
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisRateLimiter:
    def __init__(self, connection):
        self.r = connection

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        bucket = int(time.time() // window_seconds)
        rkey = f"rl:{key}:{window_seconds}:{bucket}"
        pipe = self.r.pipeline()
        pipe.incr(rkey)
        pipe.expire(rkey, window_seconds + 5)
        count = pipe.execute()[0]
        if count > limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again shortly.")

    def reset(self) -> None:
        for k in self.r.scan_iter("rl:*"):
            self.r.delete(k)


class _Limiter:
    """Picks the Redis or in-memory backend at call time (settings may change in tests)."""

    def __init__(self):
        self.memory = RateLimiter()

    def _backend(self):
        from app.core.jobs import redis_connection

        conn = redis_connection()
        return RedisRateLimiter(conn) if conn is not None else self.memory

    def check(self, key: str, limit: int, window_seconds: int = 60) -> None:
        self._backend().check(key, limit, window_seconds)

    def reset(self) -> None:
        self.memory.reset()
        backend = self._backend()
        if backend is not self.memory:
            backend.reset()


limiter = _Limiter()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
