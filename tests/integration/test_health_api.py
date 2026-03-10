"""Integration tests for health and readiness endpoints."""

from unittest.mock import AsyncMock, patch


class TestLiveness:
    async def test_liveness_returns_ok(self, async_client):
        response = await async_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestReadiness:
    async def test_readiness_all_healthy(self, async_client, test_engine):
        """When both DB and Redis are healthy, readiness returns 200."""
        with (
            patch(
                "app.api.v1.endpoints.health.get_engine",
                return_value=test_engine,
            ),
            patch(
                "app.api.v1.endpoints.health.check_redis_health",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            response = await async_client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] == "ok"
        assert data["cache"] == "ok"

    async def test_readiness_redis_down(self, async_client, test_engine):
        """When Redis is down, readiness returns 503 degraded."""
        with (
            patch(
                "app.api.v1.endpoints.health.get_engine",
                return_value=test_engine,
            ),
            patch(
                "app.api.v1.endpoints.health.check_redis_health",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            response = await async_client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "ok"
        assert data["cache"] == "error"

    async def test_readiness_db_down(self, async_client):
        """When the DB is unreachable, readiness returns 503 degraded."""
        with (
            patch(
                "app.api.v1.endpoints.health.get_engine",
                side_effect=Exception("DB unavailable"),
            ),
            patch(
                "app.api.v1.endpoints.health.check_redis_health",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            response = await async_client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "error"
        assert data["cache"] == "ok"


class TestMetricsEndpoint:
    async def test_metrics_returns_prometheus_format(self, async_client):
        """The /metrics endpoint must return Prometheus text exposition format."""
        response = await async_client.get("/metrics")
        assert response.status_code == 200
        body = response.text
        # Prometheus format includes these standard metric families
        assert "http_request_duration" in body or "http_requests" in body
        assert "# HELP" in body or "# TYPE" in body
