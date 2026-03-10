import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class EventType(StrEnum):
    ALLOCATION = "ALLOCATION"
    REDEMPTION = "REDEMPTION"
    TRANSFER = "TRANSFER"
    VALUATION_UPDATE = "VALUATION_UPDATE"


class AssetClass(StrEnum):
    PRIVATE_EQUITY = "PRIVATE_EQUITY"
    REAL_ESTATE = "REAL_ESTATE"
    HEDGE_FUND = "HEDGE_FUND"
    FIXED_INCOME = "FIXED_INCOME"
    EQUITY = "EQUITY"


class EventStatus(StrEnum):
    """PENDING and FAILED are reserved for future async processing pipeline."""

    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class InvestmentEvent(Base):
    __tablename__ = "investment_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, name="event_type_enum"), nullable=False
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(
        Enum(AssetClass, name="asset_class_enum"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="SAR")
    fx_rate_to_sar: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("1.0")
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="event_status_enum"),
        nullable=False,
        default=EventStatus.PROCESSED,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_amount_positive"),
        Index("ix_investment_events_asset_id", "asset_id"),
        Index("ix_investment_events_portfolio_id", "portfolio_id"),
        Index("ix_investment_events_asset_class", "asset_class"),
        Index("ix_investment_events_event_type", "event_type"),
        Index("ix_investment_events_created_at", "created_at"),
        Index(
            "ix_investment_events_portfolio_asset_class",
            "portfolio_id",
            "asset_class",
        ),
    )
