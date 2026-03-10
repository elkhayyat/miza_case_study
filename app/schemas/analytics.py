import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.event import AssetClass
from app.schemas.event import EventBaseResponse


class AssetClassExposure(BaseModel):
    asset_class: AssetClass
    amount_sar: Decimal
    allocation_pct: float = Field(ge=0, le=100)
    event_count: int


class PortfolioExposureResponse(BaseModel):
    portfolio_id: uuid.UUID
    total_aum_sar: Decimal
    currency: str = "SAR"
    exposures: list[AssetClassExposure]
    as_of: datetime
    cache_hit: bool = False


class PortfolioSummaryResponse(BaseModel):
    portfolio_id: uuid.UUID
    total_aum_sar: Decimal
    total_events: int
    allocations: int
    redemptions: int
    transfers: int
    valuation_updates: int
    last_event_at: datetime | None
    as_of: datetime
    cache_hit: bool = False


class EventListItem(EventBaseResponse):
    """Lightweight event representation for list views."""


class EventsListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    events: list[EventListItem]


class GlobalAggregateResponse(BaseModel):
    total_aum_sar: Decimal
    total_portfolios: int
    total_events: int
    exposures_by_asset_class: list[AssetClassExposure]
    as_of: datetime
    cache_hit: bool = False
