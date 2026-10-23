"""Background jobs.

``enqueue`` sends work to an RQ queue when ``REDIS_URL`` is configured (run
workers with ``rq worker default --url $REDIS_URL``). Otherwise the job runs
in-process after the HTTP response (FastAPI background task) or immediately
when no background context is available (CLI, tests).

Job functions must be importable module-level callables taking only
picklable arguments (ids and storage keys, never temp paths), because the
worker may run in a different container from the API.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache

from fastapi import BackgroundTasks

from app.core.config import get_settings

log = logging.getLogger("jobs")


@lru_cache
def redis_connection():
    url = get_settings().redis_url
    if not url:
        return None
    if url.startswith("fakeredis://"):  # tests
        import fakeredis

        return fakeredis.FakeStrictRedis()
    from redis import Redis

    return Redis.from_url(url)


def queue(name: str = "default"):
    from rq import Queue

    return Queue(name, connection=redis_connection())


def enqueue(func: Callable, *args, background: BackgroundTasks | None = None, timeout: int = 3600) -> str:
    """Run ``func(*args)`` in the background. Returns how it was scheduled."""
    if redis_connection() is not None:
        from rq import Retry

        queue().enqueue(func, *args, job_timeout=timeout, retry=Retry(max=3, interval=[30, 120, 600]))
        return "queued"
    if background is not None:
        background.add_task(func, *args)
        return "background"
    func(*args)
    return "inline"
