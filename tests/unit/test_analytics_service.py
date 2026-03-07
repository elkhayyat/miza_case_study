"""Unit tests for the analytics computation service."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models.event import AssetClass, EventStatus, EventType, InvestmentEvent
from app.services.analytics_service import (
    get_global_aggregate,
    get_portfolio_exposure,
    get_portfolio_summary,
    list_events,
)


async def _persist_event(
    db_session,
    portfolio_id: uuid.UUID,
    asset_class: AssetClass,
    amount: Decimal | int | float,
    event_type: EventType = EventType.ALLOCATION,
    fx_rate: Decimal | float = Decimal("1.0"),
) -> InvestmentEvent:
    now = datetime.now(UTC)
    event = InvestmentEvent(
        event_id=uuid.uuid4(),
        event_type=event_type,
        portfolio_id=portfolio_id,
        asset_id=uuid.uuid4(),
        asset_class=asset_class,
        amount=Decimal(str(amount)),
        currency="SAR",
        fx_rate_to_sar=Decimal(str(fx_rate)),
        status=EventStatus.PROCESSED,
        created_at=now,
        ingested_at=now,
        processed_at=now,
    )
    db_session.add(event)
    await db_session.flush()
    return event


class TestGetPortfolioExposure:
    async def test_empty_portfolio(self, db_session):
        portfolio_id = uuid.uuid4()
        result = await get_portfolio_exposure(db_session, portfolio_id)

        assert result.portfolio_id == portfolio_id
        assert result.total_aum_sar == Decimal("0")
        assert result.exposures == []

    async def test_single_asset_class(self, db_session):
        portfolio_id = uuid.uuid4()
        await _persist_event(db_session, portfolio_id, AssetClass.PRIVATE_EQUITY, 500000)
        await _persist_event(db_session, portfolio_id, AssetClass.PRIVATE_EQUITY, 300000)

        result = await get_portfolio_exposure(db_session, portfolio_id)

        assert result.total_aum_sar == Decimal("800000")
        assert len(result.exposures) == 1
        assert result.exposures[0].asset_class == AssetClass.PRIVATE_EQUITY
        assert result.exposures[0].allocation_pct == 100.0

    async def test_multiple_asset_classes(self, db_session):
        portfolio_id = uuid.uuid4()
        await _persist_event(db_session, portfolio_id, AssetClass.PRIVATE_EQUITY, 600000)
        await _persist_event(db_session, portfolio_id, AssetClass.REAL_ESTATE, 400000)

        result = await get_portfolio_exposure(db_session, portfolio_id)

        assert result.total_aum_sar == Decimal("1000000")
        assert len(result.exposures) == 2

        pe = next(e for e in result.exposures if e.asset_class == AssetClass.PRIVATE_EQUITY)
        re = next(e for e in result.exposures if e.asset_class == AssetClass.REAL_ESTATE)
        assert pe.allocation_pct == 60.0
        assert re.allocation_pct == 40.0

    async def test_fx_conversion_applied(self, db_session):
        portfolio_id = uuid.uuid4()
        # 1000 USD at 3.75 = 3750 SAR
        await _persist_event(db_session, portfolio_id, AssetClass.EQUITY, 1000.0, fx_rate=3.75)

        result = await get_portfolio_exposure(db_session, portfolio_id)
        assert result.total_aum_sar == Decimal("3750")

    async def test_isolation_between_portfolios(self, db_session):
        p1 = uuid.uuid4()
        p2 = uuid.uuid4()
        await _persist_event(db_session, p1, AssetClass.HEDGE_FUND, 1000000)
        await _persist_event(db_session, p2, AssetClass.FIXED_INCOME, 500000)

        r1 = await get_portfolio_exposure(db_session, p1)
        r2 = await get_portfolio_exposure(db_session, p2)

        assert r1.total_aum_sar == Decimal("1000000")
        assert r2.total_aum_sar == Decimal("500000")


class TestGetPortfolioSummary:
    async def test_empty_portfolio(self, db_session):
        result = await get_portfolio_summary(db_session, uuid.uuid4())
        assert result.total_aum_sar == Decimal("0")
        assert result.total_events == 0

    async def test_event_type_counts(self, db_session):
        portfolio_id = uuid.uuid4()
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 100000, EventType.ALLOCATION
        )
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 50000, EventType.REDEMPTION
        )
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 200000, EventType.ALLOCATION
        )

        result = await get_portfolio_summary(db_session, portfolio_id)
        assert result.total_events == 3
        assert result.allocations == 2
        assert result.redemptions == 1
        assert result.transfers == 0


class TestListEvents:
    async def test_list_all_events(self, db_session):
        portfolio_id = uuid.uuid4()
        for _ in range(5):
            await _persist_event(db_session, portfolio_id, AssetClass.EQUITY, 10000)

        result = await list_events(db_session, portfolio_id=portfolio_id)
        assert result.total == 5
        assert len(result.events) == 5

    async def test_filter_by_asset_class(self, db_session):
        portfolio_id = uuid.uuid4()
        await _persist_event(db_session, portfolio_id, AssetClass.EQUITY, 10000)
        await _persist_event(db_session, portfolio_id, AssetClass.REAL_ESTATE, 20000)

        result = await list_events(
            db_session,
            portfolio_id=portfolio_id,
            asset_class=AssetClass.EQUITY,
        )
        assert result.total == 1
        assert result.events[0].asset_class == AssetClass.EQUITY

    async def test_pagination(self, db_session):
        portfolio_id = uuid.uuid4()
        for _ in range(10):
            await _persist_event(db_session, portfolio_id, AssetClass.EQUITY, 5000)

        page1 = await list_events(db_session, portfolio_id=portfolio_id, page=1, page_size=6)
        page2 = await list_events(db_session, portfolio_id=portfolio_id, page=2, page_size=6)

        assert page1.total == 10
        assert len(page1.events) == 6
        assert len(page2.events) == 4


class TestGlobalAggregate:
    async def test_empty_database(self, db_session):
        result = await get_global_aggregate(db_session)
        assert result.total_aum_sar == Decimal("0")
        assert result.total_portfolios == 0
        assert result.total_events == 0

    async def test_aggregates_across_portfolios(self, db_session):
        p1, p2 = uuid.uuid4(), uuid.uuid4()
        await _persist_event(db_session, p1, AssetClass.EQUITY, 400000)
        await _persist_event(db_session, p2, AssetClass.REAL_ESTATE, 600000)

        result = await get_global_aggregate(db_session)
        assert result.total_aum_sar == Decimal("1000000")
        assert result.total_portfolios == 2
        assert result.total_events == 2
