import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.event import AssetClass, EventStatus, EventType

_MAX_METADATA_BYTES = 4096
_CREATED_AT_MAX_AGE = timedelta(days=30)
_CREATED_AT_MAX_FUTURE = timedelta(minutes=5)


class EventCreate(BaseModel):
    """Schema for creating a single investment event."""

    event_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Idempotency key — reuse to deduplicate retries",
    )
    event_type: EventType
    portfolio_id: uuid.UUID
    asset_id: str = Field(
        min_length=1,
        max_length=20,
        pattern=r"^[A-Z0-9][A-Z0-9.\-]*$",
        description="Asset identifier (ticker, ISIN, etc). Uppercase alphanumeric.",
    )
    asset_class: AssetClass
    amount: Decimal = Field(gt=0, description="Transaction amount in the given currency")
    currency: str = Field(default="SAR", min_length=3, max_length=3)
    fx_rate_to_sar: Decimal = Field(
        default=Decimal("1.0"),
        gt=0,
        description="FX rate to convert currency to SAR (1.0 for SAR)",
    )
    created_at: AwareDatetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Event timestamp (client-side, must include timezone). Defaults to now.",
    )
    metadata: dict[str, Any] | None = Field(default=None, description="Arbitrary JSON metadata")
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("asset_id", mode="before")
    @classmethod
    def asset_id_normalise(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("created_at")
    @classmethod
    def created_at_within_bounds(cls, v: AwareDatetime) -> AwareDatetime:
        now = datetime.now(UTC)
        if v < now - _CREATED_AT_MAX_AGE:
            msg = "created_at must not be more than 30 days in the past"
            raise ValueError(msg)
        if v > now + _CREATED_AT_MAX_FUTURE:
            msg = "created_at must not be more than 5 minutes in the future"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_metadata_size(self) -> "EventCreate":
        if self.metadata is not None:
            serialized = json.dumps(self.metadata, default=str)
            if len(serialized.encode()) > _MAX_METADATA_BYTES:
                msg = f"metadata must not exceed {_MAX_METADATA_BYTES} bytes when serialized"
                raise ValueError(msg)
        return self

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "event_type": "ALLOCATION",
                "portfolio_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "asset_id": "AAPL",
                "asset_class": "PRIVATE_EQUITY",
                "amount": "500000.00",
                "currency": "SAR",
                "fx_rate_to_sar": "1.0",
                "created_at": "2026-03-04T10:00:00Z",
                "metadata": {"deal_name": "STC Ventures Series B", "fund_id": "fund-001"},
            }
        }
    )


class EventBatchCreate(BaseModel):
    """Schema for batch event ingestion."""

    events: list[EventCreate] = Field(min_length=1, max_length=100)


class EventBaseResponse(BaseModel):
    """Shared fields across event response schemas."""

    event_id: uuid.UUID
    event_type: EventType
    portfolio_id: uuid.UUID
    asset_class: AssetClass
    amount_sar: Decimal
    currency: str
    created_at: datetime
    ingested_at: datetime


class EventResponse(EventBaseResponse):
    """Full event detail response."""

    asset_id: str
    amount: Decimal
    fx_rate_to_sar: Decimal
    status: EventStatus
    processed_at: datetime | None
    metadata: dict[str, Any] | None
    notes: str | None

    model_config = ConfigDict(from_attributes=True)


class BatchEventResponse(BaseModel):
    accepted: int
    duplicates: int
    failed: int
    events: list[EventResponse]
