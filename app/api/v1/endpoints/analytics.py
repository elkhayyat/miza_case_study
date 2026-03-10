import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import (
    cache_get,
    cache_set,
    global_aggregate_key,
    portfolio_exposure_key,
    portfolio_summary_key,
)
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
    cache_key = portfolio_exposure_key(str(portfolio_id))
    cached = await cache_get(cache_key)
    if cached:
        result = PortfolioExposureResponse(**cached)
        result.cache_hit = True
        return result

    result = await analytics_service.get_portfolio_exposure(db, portfolio_id)
    await cache_set(cache_key, result.model_dump(mode="json"))

    background_tasks.add_task(
        audit_service.write_audit_log_background,
        session_factory=get_session_factory(),
        request_id=request.state.request_id,
        action="QUERY_ANALYTICS",
        entity_type="Portfolio",
        entity_id=str(portfolio_id),
        api_key_id=api_key.client_id,
        ip_address=request.client.host if request.client else "unknown",
    )
    return result


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
    cache_key = portfolio_summary_key(str(portfolio_id))
    cached = await cache_get(cache_key)
    if cached:
        result = PortfolioSummaryResponse(**cached)
        result.cache_hit = True
        return result

    result = await analytics_service.get_portfolio_summary(db, portfolio_id)
    await cache_set(cache_key, result.model_dump(mode="json"))

    background_tasks.add_task(
        audit_service.write_audit_log_background,
        session_factory=get_session_factory(),
        request_id=request.state.request_id,
        action="QUERY_ANALYTICS",
        entity_type="Portfolio",
        entity_id=str(portfolio_id),
        api_key_id=api_key.client_id,
        ip_address=request.client.host if request.client else "unknown",
    )
    return result


@router.get(
    "/analytics/events",
    response_model=EventsListResponse,
    tags=["Analytics"],
    summary="Paginated investment event stream with filters",
)
@limiter.limit("200/minute")
async def list_events(
    request: Request,
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
    cache_key = global_aggregate_key()
    cached = await cache_get(cache_key)
    if cached:
        result = GlobalAggregateResponse(**cached)
        result.cache_hit = True
        return result

    result = await analytics_service.get_global_aggregate(db)
    await cache_set(cache_key, result.model_dump(mode="json"))

    background_tasks.add_task(
        audit_service.write_audit_log_background,
        session_factory=get_session_factory(),
        request_id=request.state.request_id,
        action="QUERY_ANALYTICS",
        entity_type="GlobalAggregate",
        entity_id=None,
        api_key_id=api_key.client_id,
        ip_address=request.client.host if request.client else "unknown",
    )
    return result
