from __future__ import annotations

import json
from typing import Any

from redis import Redis

from app.core.config import settings


redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
JOB_QUEUE_KEY = "memoryos:jobs"


def push_session_memory(key: str, payload: dict[str, Any]) -> None:
    redis_client.lpush(key, json.dumps(payload))
    redis_client.ltrim(key, 0, 199)
    redis_client.expire(key, settings.session_ttl_seconds)


def fetch_session_memory(key: str) -> list[dict[str, Any]]:
    items = redis_client.lrange(key, 0, 199)
    return [json.loads(item) for item in items]


def enqueue_job(payload: dict[str, Any]) -> None:
    redis_client.rpush(JOB_QUEUE_KEY, json.dumps(payload))


def dequeue_job(timeout_seconds: int = 3) -> dict[str, Any] | None:
    item = redis_client.blpop(JOB_QUEUE_KEY, timeout=timeout_seconds)
    if item is None:
        return None
    return json.loads(item[1])


def rate_limit_check(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    current = redis_client.incr(key)
    if current == 1:
        redis_client.expire(key, window_seconds)
    ttl = redis_client.ttl(key)
    return current <= limit, max(ttl, 0)
