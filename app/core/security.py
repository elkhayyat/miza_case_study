import hashlib
import hmac
from dataclasses import dataclass
from functools import lru_cache

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import get_settings

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=True)


@dataclass
class APIKeyInfo:
    client_id: str


@lru_cache(maxsize=1)
def _load_api_keys() -> tuple[tuple[str, str], ...]:
    """Return tuple of (hashed_key, client_id) pairs."""
    settings = get_settings()
    result: list[tuple[str, str]] = []
    if not settings.api_keys:
        return tuple(result)
    for pair in settings.api_keys.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        client_id, hashed = pair.split(":", 1)
        result.append((hashed.strip(), client_id.strip()))
    return tuple(result)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def require_api_key(raw_key: str = Security(API_KEY_HEADER)) -> APIKeyInfo:
    hashed = hash_api_key(raw_key)
    for stored_hash, client_id in _load_api_keys():
        if hmac.compare_digest(hashed, stored_hash):
            return APIKeyInfo(client_id=client_id)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )
