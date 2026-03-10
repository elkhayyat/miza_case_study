"""
Test fixtures shared across unit and integration tests.

Uses SQLite (aiosqlite) as the in-memory database for speed.
Redis is mocked to avoid requiring a live Redis instance.
"""

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.event import AssetClass, EventStatus, EventType, InvestmentEvent

# ---------------------------------------------------------------------------
# PostgreSQL test URL (set via environment variable)
# ---------------------------------------------------------------------------
POSTGRES_TEST_URL = os.environ.get("TEST_DATABASE_URL")

# ---------------------------------------------------------------------------
# In-memory SQLite engine for tests
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# API key fixtures
# ---------------------------------------------------------------------------
TEST_RAW_API_KEY = "test-api-key-12345"
TEST_CLIENT_ID = "test_client"


@pytest.fixture
def api_key_env(monkeypatch):
    """Patch the API_KEYS env var with a known test key."""
    from app.core.security import _load_api_keys, hash_api_key

    hashed = hash_api_key(TEST_RAW_API_KEY)
    monkeypatch.setenv("API_KEYS", f"{TEST_CLIENT_ID}:{hashed}")
    # Clear caches so they pick up the new env var
    from app.core.config import get_settings

    get_settings.cache_clear()
    _load_api_keys.cache_clear()
    yield
    get_settings.cache_clear()
    _load_api_keys.cache_clear()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": TEST_RAW_API_KEY}


# ---------------------------------------------------------------------------
# Mock Redis (no live Redis needed in tests)
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_redis():
    """Replace cache operations with no-ops."""
    with (
        patch("app.cache.redis_client.cache_get", new_callable=AsyncMock, return_value=None),
        patch("app.cache.redis_client.cache_set", new_callable=AsyncMock),
        patch("app.cache.redis_client.cache_delete_many", new_callable=AsyncMock),
        patch(
            "app.cache.redis_client.check_redis_health", new_callable=AsyncMock, return_value=True
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# HTTP test client with DB override
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def async_client(
    test_engine, db_session, api_key_env, mock_redis
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    test_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    app.dependency_overrides[get_db] = override_get_db
    with patch("app.db.session.get_session_factory", return_value=test_factory):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------
def make_event_data(
    portfolio_id: uuid.UUID | None = None,
    event_type: EventType = EventType.ALLOCATION,
    asset_class: AssetClass = AssetClass.PRIVATE_EQUITY,
    amount: Decimal = Decimal("100000"),
    currency: str = "SAR",
) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type.value,
        "portfolio_id": str(portfolio_id or uuid.uuid4()),
        "asset_id": "AAPL",
        "asset_class": asset_class.value,
        "amount": str(amount),
        "currency": currency,
        "fx_rate_to_sar": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
    }


@pytest_asyncio.fixture
async def sample_event(db_session) -> InvestmentEvent:
    """A pre-persisted event for retrieval tests."""
    now = datetime.now(UTC)
    event = InvestmentEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.ALLOCATION,
        portfolio_id=uuid.uuid4(),
        asset_id="AAPL",
        asset_class=AssetClass.PRIVATE_EQUITY,
        amount=Decimal("500000"),
        currency="SAR",
        fx_rate_to_sar=Decimal("1.0"),
        status=EventStatus.PROCESSED,
        created_at=now,
        ingested_at=now,
        processed_at=now,
    )
    db_session.add(event)
    await db_session.flush()
    return event


# ---------------------------------------------------------------------------
# PostgreSQL fixtures (require TEST_DATABASE_URL env var)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="function")
async def pg_engine():
    if not POSTGRES_TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_async_engine(POSTGRES_TEST_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def pg_session(pg_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
