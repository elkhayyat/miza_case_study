"""Unit tests for Pydantic schemas."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.event import AssetClass, EventType
from app.schemas.event import EventBatchCreate, EventCreate


class TestEventCreate:
    def _base_data(self, **overrides) -> dict:
        data = {
            "event_type": "ALLOCATION",
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": "AAPL",
            "asset_class": "PRIVATE_EQUITY",
            "amount": "100000.00",
            "currency": "sar",  # should be uppercased
            "fx_rate_to_sar": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
        }
        data.update(overrides)
        return data

    def test_valid_event(self):
        event = EventCreate(**self._base_data())
        assert event.event_type == EventType.ALLOCATION
        assert event.asset_class == AssetClass.PRIVATE_EQUITY
        assert event.currency == "SAR"  # uppercased by validator

    def test_currency_uppercased(self):
        event = EventCreate(**self._base_data(currency="usd"))
        assert event.currency == "USD"

    def test_default_event_id_generated(self):
        event = EventCreate(**self._base_data())
        assert isinstance(event.event_id, uuid.UUID)

    def test_explicit_event_id_preserved(self):
        fixed_id = uuid.uuid4()
        event = EventCreate(**self._base_data(event_id=str(fixed_id)))
        assert event.event_id == fixed_id

    def test_amount_must_be_positive(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(amount="-500"))

    def test_amount_zero_rejected(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(amount="0"))

    def test_fx_rate_must_be_positive(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(fx_rate_to_sar="-1.0"))

    def test_optional_metadata(self):
        event = EventCreate(**self._base_data(metadata={"deal": "Series A"}))
        assert event.metadata == {"deal": "Series A"}

    def test_metadata_defaults_none(self):
        event = EventCreate(**self._base_data())
        assert event.metadata is None

    def test_invalid_event_type_rejected(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(event_type="INVALID_TYPE"))

    def test_invalid_asset_class_rejected(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(asset_class="CRYPTO"))

    def test_created_at_too_far_in_past_rejected(self):
        old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        with pytest.raises(ValueError, match="30 days in the past"):
            EventCreate(**self._base_data(created_at=old))

    def test_created_at_too_far_in_future_rejected(self):
        future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        with pytest.raises(ValueError, match="5 minutes in the future"):
            EventCreate(**self._base_data(created_at=future))

    def test_created_at_within_bounds_accepted(self):
        recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        event = EventCreate(**self._base_data(created_at=recent))
        assert event.created_at is not None

    def test_metadata_exceeds_size_limit_rejected(self):
        large_metadata = {"key": "x" * 5000}
        with pytest.raises(ValueError, match="4096 bytes"):
            EventCreate(**self._base_data(metadata=large_metadata))

    def test_metadata_within_limit_accepted(self):
        small_metadata = {"key": "value"}
        event = EventCreate(**self._base_data(metadata=small_metadata))
        assert event.metadata == {"key": "value"}

    def test_naive_datetime_rejected(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(created_at="2026-03-09T10:00:00"))

    def test_created_at_defaults_to_now(self):
        before = datetime.now(UTC)
        data = self._base_data()
        del data["created_at"]
        event = EventCreate(**data)
        after = datetime.now(UTC)
        assert before <= event.created_at <= after

    def test_asset_id_empty_string_rejected(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(asset_id=""))

    def test_asset_id_too_long_rejected(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(asset_id="A" * 21))

    def test_asset_id_max_length_accepted(self):
        event = EventCreate(**self._base_data(asset_id="A" * 20))
        assert len(event.asset_id) == 20

    def test_asset_id_uppercased(self):
        event = EventCreate(**self._base_data(asset_id="aapl"))
        assert event.asset_id == "AAPL"

    def test_asset_id_whitespace_only_rejected(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(asset_id="   "))

    def test_asset_id_special_chars_rejected(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(asset_id="AA@#"))

    def test_asset_id_with_dot_and_dash_accepted(self):
        event = EventCreate(**self._base_data(asset_id="BRK.B"))
        assert event.asset_id == "BRK.B"
        event2 = EventCreate(**self._base_data(asset_id="X-123"))
        assert event2.asset_id == "X-123"

    def test_notes_exceeds_max_length_rejected(self):
        with pytest.raises(ValueError):
            EventCreate(**self._base_data(notes="x" * 1001))


class TestEventBatchCreate:
    def _single_event_data(self) -> dict:
        return {
            "event_type": "ALLOCATION",
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": "AAPL",
            "asset_class": "PRIVATE_EQUITY",
            "amount": "50000",
            "currency": "SAR",
            "fx_rate_to_sar": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
        }

    def test_batch_with_single_event(self):
        batch = EventBatchCreate(events=[self._single_event_data()])
        assert len(batch.events) == 1

    def test_empty_batch_rejected(self):
        with pytest.raises(ValueError):
            EventBatchCreate(events=[])

    def test_batch_with_100_events(self):
        events = [self._single_event_data() for _ in range(100)]
        batch = EventBatchCreate(events=events)
        assert len(batch.events) == 100

    def test_batch_exceeds_max_length_rejected(self):
        events = [self._single_event_data() for _ in range(101)]
        with pytest.raises(ValueError):
            EventBatchCreate(events=events)
