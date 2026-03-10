"""PostgreSQL-specific integration tests.

These tests verify behaviors that SQLite cannot catch:
- Native UUID round-trip
- Numeric precision with large amounts
- CHECK constraint enforcement at the DB level
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.event import AssetClass, EventStatus, EventType, InvestmentEvent

pytestmark = pytest.mark.postgres


async def test_uuid_roundtrip(pg_session):
    """Verify native PostgreSQL UUID storage and retrieval."""
    event_id = uuid.uuid4()
    now = datetime.now(UTC)
    event = InvestmentEvent(
        event_id=event_id,
        event_type=EventType.ALLOCATION,
        portfolio_id=uuid.uuid4(),
        asset_id=uuid.uuid4(),
        asset_class=AssetClass.PRIVATE_EQUITY,
        amount=Decimal("100000"),
        currency="SAR",
        fx_rate_to_sar=Decimal("1.0"),
        status=EventStatus.PROCESSED,
        created_at=now,
        ingested_at=now,
        processed_at=now,
    )
    pg_session.add(event)
    await pg_session.flush()

    result = await pg_session.execute(
        select(InvestmentEvent).where(InvestmentEvent.event_id == event_id)
    )
    loaded = result.scalar_one()
    assert loaded.event_id == event_id
    assert isinstance(loaded.event_id, uuid.UUID)


async def test_large_amount_precision(pg_session):
    """Verify Numeric(20,6) handles 14 integer + 6 decimal digits."""
    large_amount = Decimal("12345678901234.567890")
    now = datetime.now(UTC)
    event = InvestmentEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.ALLOCATION,
        portfolio_id=uuid.uuid4(),
        asset_id=uuid.uuid4(),
        asset_class=AssetClass.REAL_ESTATE,
        amount=large_amount,
        currency="SAR",
        fx_rate_to_sar=Decimal("1.0"),
        status=EventStatus.PROCESSED,
        created_at=now,
        ingested_at=now,
        processed_at=now,
    )
    pg_session.add(event)
    await pg_session.flush()

    result = await pg_session.execute(
        select(InvestmentEvent).where(InvestmentEvent.event_id == event.event_id)
    )
    loaded = result.scalar_one()
    assert loaded.amount == large_amount


async def test_negative_amount_rejected_by_db(pg_session):
    """Verify CHECK constraint (amount > 0) raises IntegrityError."""
    now = datetime.now(UTC)
    event = InvestmentEvent(
        event_id=uuid.uuid4(),
        event_type=EventType.REDEMPTION,
        portfolio_id=uuid.uuid4(),
        asset_id=uuid.uuid4(),
        asset_class=AssetClass.EQUITY,
        amount=Decimal("-500"),
        currency="SAR",
        fx_rate_to_sar=Decimal("1.0"),
        status=EventStatus.PROCESSED,
        created_at=now,
        ingested_at=now,
        processed_at=now,
    )
    pg_session.add(event)
    with pytest.raises(IntegrityError):
        await pg_session.flush()
