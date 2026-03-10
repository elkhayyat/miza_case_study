"""Unit tests for the analytics computation service."""

import uuid
from datetime import UTC, datetime, timedelta
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
    created_at: datetime | None = None,
    asset_id: str = "AAPL",
) -> InvestmentEvent:
    now = datetime.now(UTC)
    event = InvestmentEvent(
        event_id=uuid.uuid4(),
        event_type=event_type,
        portfolio_id=portfolio_id,
        asset_id=asset_id,
        asset_class=asset_class,
        amount=Decimal(str(amount)),
        currency="SAR",
        fx_rate_to_sar=Decimal(str(fx_rate)),
        status=EventStatus.PROCESSED,
        created_at=created_at or now,
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

    async def test_redemption_subtracts_from_aum(self, db_session):
        portfolio_id = uuid.uuid4()
        await _persist_event(
            db_session, portfolio_id, AssetClass.PRIVATE_EQUITY, 500000, EventType.ALLOCATION
        )
        await _persist_event(
            db_session, portfolio_id, AssetClass.PRIVATE_EQUITY, 100000, EventType.REDEMPTION
        )

        result = await get_portfolio_exposure(db_session, portfolio_id)
        # 500K alloc - 100K redemption = 400K
        assert result.total_aum_sar == Decimal("400000")

    async def test_isolation_between_portfolios(self, db_session):
        p1 = uuid.uuid4()
        p2 = uuid.uuid4()
        await _persist_event(db_session, p1, AssetClass.HEDGE_FUND, 1000000)
        await _persist_event(db_session, p2, AssetClass.FIXED_INCOME, 500000)

        r1 = await get_portfolio_exposure(db_session, p1)
        r2 = await get_portfolio_exposure(db_session, p2)

        assert r1.total_aum_sar == Decimal("1000000")
        assert r2.total_aum_sar == Decimal("500000")

    async def test_negative_aum_clamped(self, db_session):
        """When redemptions exceed allocations, allocation_pct should be 0.0."""
        portfolio_id = uuid.uuid4()
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 100000, EventType.ALLOCATION
        )
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 200000, EventType.REDEMPTION
        )

        result = await get_portfolio_exposure(db_session, portfolio_id)
        assert result.total_aum_sar == Decimal("-100000")
        assert len(result.exposures) == 1
        assert result.exposures[0].allocation_pct == 0.0


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
        # AUM: 100K + 200K alloc - 50K redemption = 250K
        assert result.total_aum_sar == Decimal("250000")


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

    async def test_filter_by_from_date(self, db_session):
        portfolio_id = uuid.uuid4()
        now = datetime.now(UTC)
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 10000, created_at=now - timedelta(days=5)
        )
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 20000, created_at=now - timedelta(days=1)
        )

        result = await list_events(
            db_session, portfolio_id=portfolio_id, from_date=now - timedelta(days=3)
        )
        assert result.total == 1

    async def test_filter_by_to_date(self, db_session):
        portfolio_id = uuid.uuid4()
        now = datetime.now(UTC)
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 10000, created_at=now - timedelta(days=5)
        )
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 20000, created_at=now - timedelta(days=1)
        )

        result = await list_events(
            db_session, portfolio_id=portfolio_id, to_date=now - timedelta(days=3)
        )
        assert result.total == 1

    async def test_filter_by_date_range(self, db_session):
        portfolio_id = uuid.uuid4()
        now = datetime.now(UTC)
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 10000, created_at=now - timedelta(days=10)
        )
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 20000, created_at=now - timedelta(days=5)
        )
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 30000, created_at=now - timedelta(days=1)
        )

        result = await list_events(
            db_session,
            portfolio_id=portfolio_id,
            from_date=now - timedelta(days=7),
            to_date=now - timedelta(days=2),
        )
        assert result.total == 1

    async def test_inverted_date_range_returns_empty(self, db_session):
        portfolio_id = uuid.uuid4()
        now = datetime.now(UTC)
        await _persist_event(
            db_session, portfolio_id, AssetClass.EQUITY, 10000, created_at=now - timedelta(days=3)
        )

        result = await list_events(
            db_session,
            portfolio_id=portfolio_id,
            from_date=now - timedelta(days=1),
            to_date=now - timedelta(days=5),
        )
        assert result.total == 0


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

    async def test_global_aggregate_with_redemptions(self, db_session):
        p1, p2 = uuid.uuid4(), uuid.uuid4()
        await _persist_event(db_session, p1, AssetClass.EQUITY, 500000, EventType.ALLOCATION)
        await _persist_event(db_session, p1, AssetClass.EQUITY, 100000, EventType.REDEMPTION)
        await _persist_event(db_session, p2, AssetClass.REAL_ESTATE, 300000, EventType.ALLOCATION)

        result = await get_global_aggregate(db_session)
        # 500K - 100K + 300K = 700K
        assert result.total_aum_sar == Decimal("700000")
        assert result.total_portfolios == 2
        assert result.total_events == 3
