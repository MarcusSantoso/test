from __future__ import annotations

import os
from typing import Optional

from redis import asyncio as redis

_redis_client: Optional[redis.Redis] = None


def _read_redis_url() -> str:
    url = os.getenv("REDIS_URL")
    if not url:
        raise RuntimeError("REDIS_URL environment variable is not set")
    return url


def get_redis() -> redis.Redis:
    """
    Lazily initialize and return a shared async Redis client.
    """
    global _redis_client
    if _redis_client is None:
        redis_url = _read_redis_url()
        _redis_client = redis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client

