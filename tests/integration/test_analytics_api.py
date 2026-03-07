"""Integration tests for the analytics API endpoints."""

import uuid
from datetime import UTC, datetime

import pytest

BASE = "/api/v1"


async def _create_event(
    client, headers, portfolio_id, asset_class, amount, event_type="ALLOCATION"
):
    payload = {
        "event_type": event_type,
        "portfolio_id": str(portfolio_id),
        "asset_id": str(uuid.uuid4()),
        "asset_class": asset_class,
        "amount": str(amount),
        "currency": "SAR",
        "fx_rate_to_sar": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
    }
    response = await client.post(f"{BASE}/events", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


class TestPortfolioExposure:
    async def test_exposure_empty_portfolio(self, async_client, auth_headers):
        response = await async_client.get(
            f"{BASE}/analytics/portfolio/{uuid.uuid4()}/exposure",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_aum_sar"] == "0"
        assert data["exposures"] == []

    async def test_exposure_with_events(self, async_client, auth_headers):
        portfolio_id = uuid.uuid4()
        await _create_event(async_client, auth_headers, portfolio_id, "PRIVATE_EQUITY", 600000)
        await _create_event(async_client, auth_headers, portfolio_id, "REAL_ESTATE", 400000)

        response = await async_client.get(
            f"{BASE}/analytics/portfolio/{portfolio_id}/exposure",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert float(data["total_aum_sar"]) == pytest.approx(1_000_000.0)
        assert len(data["exposures"]) == 2

    async def test_exposure_allocation_percentages(self, async_client, auth_headers):
        portfolio_id = uuid.uuid4()
        await _create_event(async_client, auth_headers, portfolio_id, "EQUITY", 750000)
        await _create_event(async_client, auth_headers, portfolio_id, "HEDGE_FUND", 250000)

        response = await async_client.get(
            f"{BASE}/analytics/portfolio/{portfolio_id}/exposure",
            headers=auth_headers,
        )
        data = response.json()
        total_pct = sum(e["allocation_pct"] for e in data["exposures"])
        assert total_pct == pytest.approx(100.0, rel=0.01)

    async def test_exposure_requires_auth(self, async_client):
        response = await async_client.get(f"{BASE}/analytics/portfolio/{uuid.uuid4()}/exposure")
        assert response.status_code == 401


class TestPortfolioSummary:
    async def test_summary_empty(self, async_client, auth_headers):
        response = await async_client.get(
            f"{BASE}/analytics/portfolio/{uuid.uuid4()}/summary",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_events"] == 0
        assert data["total_aum_sar"] == "0"

    async def test_summary_with_mixed_events(self, async_client, auth_headers):
        portfolio_id = uuid.uuid4()
        await _create_event(
            async_client, auth_headers, portfolio_id, "EQUITY", 200000, "ALLOCATION"
        )
        await _create_event(async_client, auth_headers, portfolio_id, "EQUITY", 50000, "REDEMPTION")
        await _create_event(
            async_client, auth_headers, portfolio_id, "REAL_ESTATE", 100000, "ALLOCATION"
        )

        response = await async_client.get(
            f"{BASE}/analytics/portfolio/{portfolio_id}/summary",
            headers=auth_headers,
        )
        data = response.json()
        assert data["total_events"] == 3
        assert data["allocations"] == 2
        assert data["redemptions"] == 1


class TestEventsList:
    async def test_list_events_empty(self, async_client, auth_headers):
        response = await async_client.get(f"{BASE}/analytics/events", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["events"] == []

    async def test_list_events_with_filter(self, async_client, auth_headers):
        portfolio_id = uuid.uuid4()
        await _create_event(async_client, auth_headers, portfolio_id, "EQUITY", 100000)
        await _create_event(async_client, auth_headers, portfolio_id, "REAL_ESTATE", 200000)

        response = await async_client.get(
            f"{BASE}/analytics/events",
            params={"portfolio_id": str(portfolio_id), "asset_class": "EQUITY"},
            headers=auth_headers,
        )
        data = response.json()
        assert data["total"] == 1
        assert data["events"][0]["asset_class"] == "EQUITY"

    async def test_list_events_pagination(self, async_client, auth_headers):
        portfolio_id = uuid.uuid4()
        for _ in range(8):
            await _create_event(async_client, auth_headers, portfolio_id, "EQUITY", 10000)

        r1 = await async_client.get(
            f"{BASE}/analytics/events",
            params={"portfolio_id": str(portfolio_id), "page": 1, "page_size": 5},
            headers=auth_headers,
        )
        r2 = await async_client.get(
            f"{BASE}/analytics/events",
            params={"portfolio_id": str(portfolio_id), "page": 2, "page_size": 5},
            headers=auth_headers,
        )
        assert len(r1.json()["events"]) == 5
        assert len(r2.json()["events"]) == 3


class TestGlobalAggregate:
    async def test_global_aggregate_empty(self, async_client, auth_headers):
        response = await async_client.get(f"{BASE}/analytics/aggregate", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total_portfolios"] == 0
        assert data["total_events"] == 0

    async def test_global_aggregate_with_data(self, async_client, auth_headers):
        p1 = uuid.uuid4()
        p2 = uuid.uuid4()
        await _create_event(async_client, auth_headers, p1, "EQUITY", 300000)
        await _create_event(async_client, auth_headers, p2, "REAL_ESTATE", 700000)

        response = await async_client.get(f"{BASE}/analytics/aggregate", headers=auth_headers)
        data = response.json()
        assert data["total_portfolios"] == 2
        assert float(data["total_aum_sar"]) == pytest.approx(1_000_000.0)
