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
        "asset_id": "AAPL",
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
            "app.services.event_service.cache_delete_many", new_callable=AsyncMock
        ) as mock_del:
            data = _make_event_create()
            await ingest_event(db_session, data)
            assert mock_del.called

    async def test_concurrent_duplicate_handled(self, db_session, mock_redis):
        """TOCTOU: when SELECT misses a concurrent insert, IntegrityError is caught."""
        from app.services import event_service

        data = _make_event_create()
        event1, _ = await ingest_event(db_session, data)
        await db_session.commit()

        # Save original before patching
        real_get = event_service.get_event_by_id
        call_count = 0

        async def mock_get(db, event_id):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # Simulate race: not found on first check
            return await real_get(db, event_id)

        with patch.object(event_service, "get_event_by_id", side_effect=mock_get):
            event2, is_dup = await ingest_event(db_session, data)

        assert is_dup is True
        assert event2.event_id == event1.event_id


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

    async def test_concurrent_duplicate_counted_as_duplicate(self, db_session, mock_redis):
        """IntegrityError from concurrent insert should count as duplicate, not failed."""
        from app.services import event_service

        data = _make_event_create()
        await ingest_event(db_session, data)
        await db_session.commit()

        # Dedup check misses the event (simulates concurrent insert race)
        with patch.object(event_service, "_get_existing_event_ids", return_value={}):
            processed, dups, failed = await ingest_batch(db_session, [data])

        assert dups == 1
        assert failed == 0
        assert len(processed) == 1
        assert processed[0].event_id == data.event_id

    async def test_batch_continues_after_integrity_error(self, db_session, mock_redis):
        """Session remains usable for subsequent events after savepoint rollback."""
        from app.services import event_service

        existing = _make_event_create()
        await ingest_event(db_session, existing)
        await db_session.commit()

        new_event = _make_event_create()
        batch = [existing, new_event]

        with patch.object(event_service, "_get_existing_event_ids", return_value={}):
            processed, dups, failed = await ingest_batch(db_session, batch)

        assert dups == 1
        assert failed == 0
        assert len(processed) == 2
        # Second event was inserted successfully after the first hit IntegrityError
        event_ids = {e.event_id for e in processed}
        assert existing.event_id in event_ids
        assert new_event.event_id in event_ids

    async def test_batch_unexpected_error_counted_as_failed(self, db_session, mock_redis):
        """An unexpected exception for one event should count as failed, not crash the batch."""
        from app.services import event_service

        good1 = _make_event_create()
        bad = _make_event_create()
        good2 = _make_event_create()

        original_build = event_service._build_event

        def exploding_build(data):
            if data.event_id == bad.event_id:
                raise RuntimeError("simulated failure")
            return original_build(data)

        with patch.object(event_service, "_build_event", side_effect=exploding_build):
            processed, dups, failed = await ingest_batch(db_session, [good1, bad, good2])

        assert failed == 1
        assert dups == 0
        assert len(processed) == 2
        event_ids = {e.event_id for e in processed}
        assert good1.event_id in event_ids
        assert good2.event_id in event_ids


class TestComputeAmountSar:
    def test_sar_currency_no_conversion(self):
        event = InvestmentEvent(
            event_id=uuid.uuid4(),
            event_type=EventType.ALLOCATION,
            portfolio_id=uuid.uuid4(),
            asset_id="AAPL",
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
            asset_id="AAPL",
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

    def test_redemption_returns_negative(self):
        event = InvestmentEvent(
            event_id=uuid.uuid4(),
            event_type=EventType.REDEMPTION,
            portfolio_id=uuid.uuid4(),
            asset_id="AAPL",
            asset_class=AssetClass.EQUITY,
            amount=Decimal("50000"),
            currency="SAR",
            fx_rate_to_sar=Decimal("1.0"),
            status=EventStatus.PROCESSED,
            created_at=datetime.now(UTC),
            ingested_at=datetime.now(UTC),
        )
        result = compute_amount_sar(event)
        assert result == Decimal("-50000.0")
