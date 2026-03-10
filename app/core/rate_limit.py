from functools import lru_cache

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import get_settings
from app.core.security import hash_api_key


def _key_func(request: Request) -> str:
    """Key by hashed API key if present, otherwise by IP."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return hash_api_key(api_key)
    return get_remote_address(request)


@lru_cache
def get_limiter() -> Limiter:
    settings = get_settings()
    default_limit = f"{settings.rate_limit_requests}/{settings.rate_limit_window_seconds}second"
    return Limiter(
        key_func=_key_func,
        default_limits=[default_limit],
        storage_uri=settings.redis_url,
        in_memory_fallback_enabled=True,
        swallow_errors=True,
    )
