import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def cache_get(key: str) -> Any | None:
    """Retrieve a cached value. Returns None on miss or error."""
    try:
        client = get_redis()
        raw = await client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis GET failed, cache miss", extra={"key": key, "error": str(exc)})
        return None


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    """Store a value in cache. Silently fails on error."""
    try:
        settings = get_settings()
        client = get_redis()
        serialized = json.dumps(value, default=str)
        await client.set(key, serialized, ex=ttl or settings.cache_ttl_seconds)
    except Exception as exc:
        logger.warning("Redis SET failed", extra={"key": key, "error": str(exc)})


async def cache_delete(key: str) -> None:
    """Invalidate a cache key."""
    try:
        client = get_redis()
        await client.delete(key)
    except Exception as exc:
        logger.warning("Redis DELETE failed", extra={"key": key, "error": str(exc)})


async def cache_delete_pattern(pattern: str) -> None:
    """Invalidate all keys matching a glob pattern using SCAN."""
    try:
        client = get_redis()
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("Redis SCAN/DELETE failed", extra={"pattern": pattern, "error": str(exc)})


def portfolio_exposure_key(portfolio_id: str) -> str:
    return f"analytics:portfolio:{portfolio_id}:exposure"


def portfolio_summary_key(portfolio_id: str) -> str:
    return f"analytics:portfolio:{portfolio_id}:summary"


def global_aggregate_key() -> str:
    return "analytics:global:aggregate"


async def check_redis_health() -> bool:
    try:
        client = get_redis()
        await client.ping()
        return True
    except Exception:
        return False
