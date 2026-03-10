"""Unit tests for the event ingestion service."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.models.event import AssetClass, EventStatus, EventType, InvestmentEvent
from app.schemas.event import EventCreate
from app.services.event_service import compute_amount_sar, ingest_batch, ingest_event


def _make_event_create(**overrides) -> EventCreate:
    defaults = {
        "event_type": EventType.ALLOCATION,
        "portfolio_id": uuid.uuid4(),
        "asset_id": uuid.uuid4(),
        "asset_class": AssetClass.PRIVATE_EQUITY,
        "amount": Decimal("200000"),
        "currency": "SAR",
        "fx_rate_to_sar": Decimal("1.0"),
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return EventCreate(**defaults)


class TestIngestEvent:
    async def test_new_event_persisted(self, db_session, mock_redis):
        data = _make_event_create()
        event, is_dup = await ingest_event(db_session, data)

        assert not is_dup
        assert event.event_id == data.event_id
        assert event.status == EventStatus.PROCESSED
        assert event.processed_at is not None

    async def test_duplicate_event_returns_existing(self, db_session, mock_redis):
        data = _make_event_create()
        event1, is_dup1 = await ingest_event(db_session, data)
        event2, is_dup2 = await ingest_event(db_session, data)

        assert not is_dup1
        assert is_dup2
        assert event1.event_id == event2.event_id

    async def test_event_amount_stored_correctly(self, db_session, mock_redis):
        data = _make_event_create(amount=Decimal("999999.99"))
        event, _ = await ingest_event(db_session, data)
        assert event.amount == Decimal("999999.99")

    async def test_event_with_metadata(self, db_session, mock_redis):
        data = _make_event_create(metadata={"fund": "Alpha Fund"})
        event, _ = await ingest_event(db_session, data)
        assert event.metadata_ == {"fund": "Alpha Fund"}

    async def test_cache_invalidated_on_new_event(self, db_session):
        with patch(
            "app.services.event_service.cache_delete_pattern", new_callable=AsyncMock
        ) as mock_del:
            data = _make_event_create()
            await ingest_event(db_session, data)
            assert mock_del.called


class TestIngestBatch:
    async def test_batch_all_new(self, db_session, mock_redis):
        events_data = [_make_event_create() for _ in range(3)]
        processed, dups, failed = await ingest_batch(db_session, events_data)

        assert len(processed) == 3
        assert dups == 0
        assert failed == 0

    async def test_batch_with_duplicate(self, db_session, mock_redis):
        data = _make_event_create()
        await ingest_event(db_session, data)  # pre-insert

        events_data = [data, _make_event_create()]
        processed, dups, failed = await ingest_batch(db_session, events_data)

        assert dups == 1
        assert failed == 0
        assert len(processed) == 2

    async def test_empty_batch(self, db_session, mock_redis):
        processed, dups, failed = await ingest_batch(db_session, [])
        assert processed == []
        assert dups == 0


class TestComputeAmountSar:
    def test_sar_currency_no_conversion(self):
        event = InvestmentEvent(
            event_id=uuid.uuid4(),
            event_type=EventType.ALLOCATION,
            portfolio_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
            asset_class=AssetClass.PRIVATE_EQUITY,
            amount=Decimal("100000"),
            currency="SAR",
            fx_rate_to_sar=Decimal("1.0"),
            status=EventStatus.PROCESSED,
            created_at=datetime.now(UTC),
            ingested_at=datetime.now(UTC),
        )
        result = compute_amount_sar(event)
        assert result == Decimal("100000.0")

    def test_usd_conversion(self):
        event = InvestmentEvent(
            event_id=uuid.uuid4(),
            event_type=EventType.ALLOCATION,
            portfolio_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
            asset_class=AssetClass.EQUITY,
            amount=Decimal("1000"),
            currency="USD",
            fx_rate_to_sar=Decimal("3.75"),
            status=EventStatus.PROCESSED,
            created_at=datetime.now(UTC),
            ingested_at=datetime.now(UTC),
        )
        result = compute_amount_sar(event)
        assert result == Decimal("3750.00")
