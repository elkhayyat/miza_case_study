"""Integration tests for the events API endpoints."""

import uuid
from datetime import UTC, datetime

import pytest

BASE = "/api/v1"


class TestIngestEvent:
    async def test_create_event_success(self, async_client, auth_headers):
        payload = {
            "event_type": "ALLOCATION",
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": str(uuid.uuid4()),
            "asset_class": "PRIVATE_EQUITY",
            "amount": "500000.00",
            "currency": "SAR",
            "fx_rate_to_sar": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
        }
        response = await async_client.post(f"{BASE}/events", json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["event_type"] == "ALLOCATION"
        assert float(data["amount_sar"]) == pytest.approx(500000.0)
        assert data["status"] == "PROCESSED"

    async def test_idempotent_resubmission(self, async_client, auth_headers):
        event_id = str(uuid.uuid4())
        payload = {
            "event_id": event_id,
            "event_type": "ALLOCATION",
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": str(uuid.uuid4()),
            "asset_class": "EQUITY",
            "amount": "100000",
            "currency": "SAR",
            "fx_rate_to_sar": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
        }
        r1 = await async_client.post(f"{BASE}/events", json=payload, headers=auth_headers)
        r2 = await async_client.post(f"{BASE}/events", json=payload, headers=auth_headers)

        assert r1.status_code == 201
        assert r2.status_code == 200  # duplicate returns 200
        assert r1.json()["event_id"] == r2.json()["event_id"]

    async def test_missing_api_key_returns_401(self, async_client):
        payload = {
            "event_type": "ALLOCATION",
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": str(uuid.uuid4()),
            "asset_class": "EQUITY",
            "amount": "1000",
            "currency": "SAR",
            "fx_rate_to_sar": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
        }
        response = await async_client.post(f"{BASE}/events", json=payload)
        assert response.status_code == 401

    async def test_invalid_api_key_returns_401(self, async_client):
        payload = {
            "event_type": "ALLOCATION",
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": str(uuid.uuid4()),
            "asset_class": "EQUITY",
            "amount": "1000",
            "currency": "SAR",
            "fx_rate_to_sar": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
        }
        response = await async_client.post(
            f"{BASE}/events", json=payload, headers={"X-API-Key": "wrong-key"}
        )
        assert response.status_code == 401

    async def test_invalid_event_type_returns_422(self, async_client, auth_headers):
        payload = {
            "event_type": "BUY",  # invalid
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": str(uuid.uuid4()),
            "asset_class": "EQUITY",
            "amount": "1000",
            "currency": "SAR",
            "fx_rate_to_sar": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
        }
        response = await async_client.post(f"{BASE}/events", json=payload, headers=auth_headers)
        assert response.status_code == 422

    async def test_negative_amount_returns_422(self, async_client, auth_headers):
        payload = {
            "event_type": "ALLOCATION",
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": str(uuid.uuid4()),
            "asset_class": "EQUITY",
            "amount": "-1000",
            "currency": "SAR",
            "fx_rate_to_sar": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
        }
        response = await async_client.post(f"{BASE}/events", json=payload, headers=auth_headers)
        assert response.status_code == 422

    async def test_fx_conversion(self, async_client, auth_headers):
        payload = {
            "event_type": "ALLOCATION",
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": str(uuid.uuid4()),
            "asset_class": "EQUITY",
            "amount": "1000.00",
            "currency": "USD",
            "fx_rate_to_sar": "3.75",
            "created_at": datetime.now(UTC).isoformat(),
        }
        response = await async_client.post(f"{BASE}/events", json=payload, headers=auth_headers)
        assert response.status_code == 201
        assert float(response.json()["amount_sar"]) == pytest.approx(3750.0)


class TestBatchIngest:
    async def test_batch_ingest_success(self, async_client, auth_headers):
        events = [
            {
                "event_type": "ALLOCATION",
                "portfolio_id": str(uuid.uuid4()),
                "asset_id": str(uuid.uuid4()),
                "asset_class": "PRIVATE_EQUITY",
                "amount": str(i * 10000),
                "currency": "SAR",
                "fx_rate_to_sar": "1.0",
                "created_at": datetime.now(UTC).isoformat(),
            }
            for i in range(1, 4)
        ]
        response = await async_client.post(
            f"{BASE}/events/batch", json={"events": events}, headers=auth_headers
        )
        assert response.status_code == 207
        data = response.json()
        assert data["accepted"] == 3
        assert data["duplicates"] == 0
        assert data["failed"] == 0

    async def test_batch_with_duplicates(self, async_client, auth_headers):
        event_id = str(uuid.uuid4())
        event = {
            "event_id": event_id,
            "event_type": "ALLOCATION",
            "portfolio_id": str(uuid.uuid4()),
            "asset_id": str(uuid.uuid4()),
            "asset_class": "EQUITY",
            "amount": "50000",
            "currency": "SAR",
            "fx_rate_to_sar": "1.0",
            "created_at": datetime.now(UTC).isoformat(),
        }
        # First batch
        await async_client.post(
            f"{BASE}/events/batch", json={"events": [event]}, headers=auth_headers
        )
        # Second batch with same event
        response = await async_client.post(
            f"{BASE}/events/batch", json={"events": [event]}, headers=auth_headers
        )
        data = response.json()
        assert data["duplicates"] == 1
        assert data["accepted"] == 0

    async def test_batch_exceeds_max_size(self, async_client, auth_headers):
        events = [
            {
                "event_type": "ALLOCATION",
                "portfolio_id": str(uuid.uuid4()),
                "asset_id": str(uuid.uuid4()),
                "asset_class": "EQUITY",
                "amount": "1000",
                "currency": "SAR",
                "fx_rate_to_sar": "1.0",
                "created_at": datetime.now(UTC).isoformat(),
            }
            for _ in range(101)
        ]
        response = await async_client.post(
            f"{BASE}/events/batch", json={"events": events}, headers=auth_headers
        )
        assert response.status_code == 422


class TestGetEvent:
    async def test_get_existing_event(self, async_client, auth_headers, sample_event):
        response = await async_client.get(
            f"{BASE}/events/{sample_event.event_id}", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["event_id"] == str(sample_event.event_id)

    async def test_get_nonexistent_event_returns_404(self, async_client, auth_headers):
        response = await async_client.get(f"{BASE}/events/{uuid.uuid4()}", headers=auth_headers)
        assert response.status_code == 404


class TestRequestIdValidation:
    async def test_invalid_request_id_replaced(self, async_client, auth_headers):
        headers = {**auth_headers, "X-Request-ID": "not-a-uuid"}
        response = await async_client.get(f"{BASE}/events/{uuid.uuid4()}", headers=headers)
        returned_id = response.headers.get("X-Request-ID")
        assert returned_id != "not-a-uuid"
        uuid.UUID(returned_id)  # should not raise

    async def test_valid_request_id_preserved(self, async_client, auth_headers):
        valid_id = str(uuid.uuid4())
        headers = {**auth_headers, "X-Request-ID": valid_id}
        response = await async_client.get(f"{BASE}/events/{uuid.uuid4()}", headers=headers)
        assert response.headers.get("X-Request-ID") == valid_id
