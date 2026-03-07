import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import AssetClass, EventType, InvestmentEvent
from app.schemas.analytics import (
    AssetClassExposure,
    EventListItem,
    EventsListResponse,
    GlobalAggregateResponse,
    PortfolioExposureResponse,
    PortfolioSummaryResponse,
)
from app.services.event_service import amount_sar_expr, compute_amount_sar


async def get_portfolio_exposure(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
) -> PortfolioExposureResponse:
    """Compute AUM by asset class for a portfolio."""
    rows = await db.execute(
        select(
            InvestmentEvent.asset_class,
            func.sum(amount_sar_expr()).label("amount_sar"),
            func.count(InvestmentEvent.event_id).label("event_count"),
        )
        .where(InvestmentEvent.portfolio_id == portfolio_id)
        .group_by(InvestmentEvent.asset_class)
    )
    results = rows.all()

    exposures = []
    total_sar = Decimal("0")
    for row in results:
        amount = Decimal(str(row.amount_sar))
        total_sar += amount
        exposures.append((row.asset_class, amount, row.event_count))

    exposure_list = [
        AssetClassExposure(
            asset_class=ac,
            amount_sar=amount,
            allocation_pct=round(float(amount / total_sar * 100), 2) if total_sar > 0 else 0.0,
            event_count=cnt,
        )
        for ac, amount, cnt in exposures
    ]

    return PortfolioExposureResponse(
        portfolio_id=portfolio_id,
        total_aum_sar=total_sar,
        exposures=exposure_list,
        as_of=datetime.now(UTC),
    )


async def get_portfolio_summary(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
) -> PortfolioSummaryResponse:
    """Compute portfolio-level summary metrics in a single query."""
    row = await db.execute(
        select(
            func.sum(amount_sar_expr()).label("total_aum"),
            func.count(InvestmentEvent.event_id).label("total_events"),
            func.sum(
                case(
                    (InvestmentEvent.event_type == EventType.ALLOCATION, 1),
                    else_=0,
                )
            ).label("allocations"),
            func.sum(
                case(
                    (InvestmentEvent.event_type == EventType.REDEMPTION, 1),
                    else_=0,
                )
            ).label("redemptions"),
            func.sum(
                case(
                    (InvestmentEvent.event_type == EventType.TRANSFER, 1),
                    else_=0,
                )
            ).label("transfers"),
            func.sum(
                case(
                    (InvestmentEvent.event_type == EventType.VALUATION_UPDATE, 1),
                    else_=0,
                )
            ).label("valuation_updates"),
            func.max(InvestmentEvent.created_at).label("last_event_at"),
        ).where(InvestmentEvent.portfolio_id == portfolio_id)
    )
    r = row.one()

    return PortfolioSummaryResponse(
        portfolio_id=portfolio_id,
        total_aum_sar=Decimal(str(r.total_aum or 0)),
        total_events=r.total_events or 0,
        allocations=r.allocations or 0,
        redemptions=r.redemptions or 0,
        transfers=r.transfers or 0,
        valuation_updates=r.valuation_updates or 0,
        last_event_at=r.last_event_at,
        as_of=datetime.now(UTC),
    )


async def list_events(
    db: AsyncSession,
    portfolio_id: uuid.UUID | None = None,
    event_type: EventType | None = None,
    asset_class: AssetClass | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> EventsListResponse:
    """Paginated event stream with optional filters."""
    query = select(InvestmentEvent)

    if portfolio_id is not None:
        query = query.where(InvestmentEvent.portfolio_id == portfolio_id)
    if event_type is not None:
        query = query.where(InvestmentEvent.event_type == event_type)
    if asset_class is not None:
        query = query.where(InvestmentEvent.asset_class == asset_class)
    if from_date is not None:
        query = query.where(InvestmentEvent.created_at >= from_date)
    if to_date is not None:
        query = query.where(InvestmentEvent.created_at <= to_date)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    rows = await db.execute(
        query.order_by(InvestmentEvent.created_at.desc()).offset(offset).limit(page_size)
    )
    events = rows.scalars().all()

    return EventsListResponse(
        total=total,
        page=page,
        page_size=page_size,
        events=[
            EventListItem(
                event_id=e.event_id,
                event_type=e.event_type,
                portfolio_id=e.portfolio_id,
                asset_class=e.asset_class,
                amount_sar=compute_amount_sar(e),
                currency=e.currency,
                created_at=e.created_at,
                ingested_at=e.ingested_at,
            )
            for e in events
        ],
    )


async def get_global_aggregate(db: AsyncSession) -> GlobalAggregateResponse:
    """Compute global AUM and exposure across all portfolios."""
    # Single aggregate query for totals
    totals_row = await db.execute(
        select(
            func.sum(amount_sar_expr()).label("total_aum"),
            func.count(func.distinct(InvestmentEvent.portfolio_id)).label("total_portfolios"),
            func.count(InvestmentEvent.event_id).label("total_events"),
        )
    )
    totals = totals_row.one()
    total_aum = Decimal(str(totals.total_aum or 0))
    total_portfolios = totals.total_portfolios or 0
    total_events = totals.total_events or 0

    # Group-by query for asset class breakdown
    asset_rows = await db.execute(
        select(
            InvestmentEvent.asset_class,
            func.sum(amount_sar_expr()).label("amount_sar"),
            func.count(InvestmentEvent.event_id).label("event_count"),
        ).group_by(InvestmentEvent.asset_class)
    )

    exposures = [
        AssetClassExposure(
            asset_class=row.asset_class,
            amount_sar=Decimal(str(row.amount_sar)),
            allocation_pct=round(float(Decimal(str(row.amount_sar)) / total_aum * 100), 2)
            if total_aum > 0
            else 0.0,
            event_count=row.event_count,
        )
        for row in asset_rows
    ]

    return GlobalAggregateResponse(
        total_aum_sar=total_aum,
        total_portfolios=total_portfolios,
        total_events=total_events,
        exposures_by_asset_class=exposures,
        as_of=datetime.now(UTC),
    )
