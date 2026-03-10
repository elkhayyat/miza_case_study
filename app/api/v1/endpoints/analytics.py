import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import (
    GLOBAL_AGGREGATE_KEY,
    cache_get,
    cache_set,
    portfolio_exposure_key,
    portfolio_summary_key,
)
from app.core.logging import get_logger
from app.core.rate_limit import get_limiter
from app.core.security import APIKeyInfo, require_api_key
from app.db.session import get_db, get_session_factory
from app.models.event import AssetClass, EventType
from app.schemas.analytics import (
    EventsListResponse,
    GlobalAggregateResponse,
    PortfolioExposureResponse,
    PortfolioSummaryResponse,
)
from app.services import analytics_service, audit_service

router = APIRouter()
limiter = get_limiter()
logger = get_logger(__name__)


async def _cached_analytics[
    CacheableT: (PortfolioExposureResponse, PortfolioSummaryResponse, GlobalAggregateResponse)
](
    cache_key: str,
    response_type: type[CacheableT],
    compute: Callable[[], Awaitable[CacheableT]],
    background_tasks: BackgroundTasks,
    request: Request,
    api_key: APIKeyInfo,
    entity_type: str,
    entity_id: str | None,
) -> CacheableT:
    """Cache-aside helper shared by cached analytics endpoints."""
    background_tasks.add_task(
        audit_service.write_audit_log_background,
        session_factory=get_session_factory(),
        request_id=request.state.request_id,
        action="QUERY_ANALYTICS",
        entity_type=entity_type,
        entity_id=entity_id,
        api_key_id=api_key.client_id,
        ip_address=request.client.host if request.client else "unknown",
    )

    cached = await cache_get(cache_key)
    if cached is not None:
        try:
            result = response_type.model_validate(cached)
            result.cache_hit = True
            return result
        except ValidationError:
            logger.warning("Cache validation failed for key %s, falling through to DB", cache_key)

    result = await compute()
    await cache_set(cache_key, result.model_dump(mode="json"))
    return result


@router.get(
    "/analytics/portfolio/{portfolio_id}/exposure",
    response_model=PortfolioExposureResponse,
    tags=["Analytics"],
    summary="Portfolio AUM breakdown by asset class",
)
@limiter.limit("200/minute")
async def get_portfolio_exposure(
    portfolio_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    api_key: Annotated[APIKeyInfo, Depends(require_api_key)],
) -> PortfolioExposureResponse:
    return await _cached_analytics(
        cache_key=portfolio_exposure_key(str(portfolio_id)),
        response_type=PortfolioExposureResponse,
        compute=lambda: analytics_service.get_portfolio_exposure(db, portfolio_id),
        background_tasks=background_tasks,
        request=request,
        api_key=api_key,
        entity_type="Portfolio",
        entity_id=str(portfolio_id),
    )


@router.get(
    "/analytics/portfolio/{portfolio_id}/summary",
    response_model=PortfolioSummaryResponse,
    tags=["Analytics"],
    summary="Portfolio summary: total AUM and event breakdown",
)
@limiter.limit("200/minute")
async def get_portfolio_summary(
    portfolio_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    api_key: Annotated[APIKeyInfo, Depends(require_api_key)],
) -> PortfolioSummaryResponse:
    return await _cached_analytics(
        cache_key=portfolio_summary_key(str(portfolio_id)),
        response_type=PortfolioSummaryResponse,
        compute=lambda: analytics_service.get_portfolio_summary(db, portfolio_id),
        background_tasks=background_tasks,
        request=request,
        api_key=api_key,
        entity_type="Portfolio",
        entity_id=str(portfolio_id),
    )


@router.get(
    "/analytics/events",
    response_model=EventsListResponse,
    tags=["Analytics"],
    summary="Paginated investment event stream with filters",
)
@limiter.limit("200/minute")
async def list_events(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    api_key: Annotated[APIKeyInfo, Depends(require_api_key)],
    portfolio_id: uuid.UUID | None = Query(default=None),
    event_type: EventType | None = Query(default=None),
    asset_class: AssetClass | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> EventsListResponse:
    background_tasks.add_task(
        audit_service.write_audit_log_background,
        session_factory=get_session_factory(),
        request_id=request.state.request_id,
        action="QUERY_ANALYTICS",
        entity_type="EventsList",
        entity_id=str(portfolio_id) if portfolio_id else None,
        api_key_id=api_key.client_id,
        ip_address=request.client.host if request.client else "unknown",
    )
    return await analytics_service.list_events(
        db,
        portfolio_id=portfolio_id,
        event_type=event_type,
        asset_class=asset_class,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/analytics/aggregate",
    response_model=GlobalAggregateResponse,
    tags=["Analytics"],
    summary="Global AUM and asset class breakdown across all portfolios",
)
@limiter.limit("200/minute")
async def get_global_aggregate(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    api_key: Annotated[APIKeyInfo, Depends(require_api_key)],
) -> GlobalAggregateResponse:
    return await _cached_analytics(
        cache_key=GLOBAL_AGGREGATE_KEY,
        response_type=GlobalAggregateResponse,
        compute=lambda: analytics_service.get_global_aggregate(db),
        background_tasks=background_tasks,
        request=request,
        api_key=api_key,
        entity_type="GlobalAggregate",
        entity_id=None,
    )
