"""Unit tests for the audit service."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.metrics import audit_write_failures
from app.services.audit_service import (
    compute_payload_hash,
    write_audit_log,
    write_audit_log_background,
)


class TestComputePayloadHash:
    def test_none_returns_none(self):
        assert compute_payload_hash(None) is None

    def test_returns_64_char_hex(self):
        result = compute_payload_hash({"key": "value"})
        assert result is not None
        assert len(result) == 64

    def test_deterministic(self):
        payload = {"event_id": "abc", "amount": "1000"}
        h1 = compute_payload_hash(payload)
        h2 = compute_payload_hash(payload)
        assert h1 == h2

    def test_different_payloads_different_hashes(self):
        h1 = compute_payload_hash({"a": 1})
        h2 = compute_payload_hash({"a": 2})
        assert h1 != h2

    def test_key_order_independent(self):
        h1 = compute_payload_hash({"a": 1, "b": 2})
        h2 = compute_payload_hash({"b": 2, "a": 1})
        assert h1 == h2


class TestWriteAuditLog:
    async def test_log_persisted(self, db_session):
        log = await write_audit_log(
            db_session,
            request_id=str(uuid.uuid4()),
            action="CREATE_EVENT",
            entity_type="InvestmentEvent",
            entity_id=str(uuid.uuid4()),
            api_key_id="test_client",
            ip_address="127.0.0.1",
            payload={"event_id": "some-id"},
        )
        await db_session.commit()

        assert log.log_id is not None
        assert log.action == "CREATE_EVENT"
        assert log.api_key_id == "test_client"
        assert log.payload_hash is not None

    async def test_log_with_no_payload(self, db_session):
        log = await write_audit_log(
            db_session,
            request_id=str(uuid.uuid4()),
            action="QUERY_ANALYTICS",
            entity_type="Portfolio",
            entity_id=str(uuid.uuid4()),
            api_key_id="test_client",
            ip_address="10.0.0.1",
        )
        assert log.payload_hash is None

    async def test_log_entity_id_optional(self, db_session):
        log = await write_audit_log(
            db_session,
            request_id=str(uuid.uuid4()),
            action="CREATE_BATCH_EVENTS",
            entity_type="InvestmentEvent",
            entity_id=None,
            api_key_id="test_client",
            ip_address="192.168.1.1",
        )
        assert log.entity_id is None

    async def test_same_request_id_allowed(self, db_session):
        """Two audit entries with the same request_id should coexist."""
        request_id = str(uuid.uuid4())
        log1 = await write_audit_log(
            db_session,
            request_id=request_id,
            action="CREATE_EVENT",
            entity_type="InvestmentEvent",
            entity_id=str(uuid.uuid4()),
            api_key_id="test_client",
            ip_address="127.0.0.1",
        )
        log2 = await write_audit_log(
            db_session,
            request_id=request_id,
            action="QUERY_ANALYTICS",
            entity_type="Portfolio",
            entity_id=str(uuid.uuid4()),
            api_key_id="test_client",
            ip_address="127.0.0.1",
        )
        await db_session.commit()
        assert log1.log_id != log2.log_id
        assert log1.request_id == log2.request_id


class TestWriteAuditLogBackground:
    async def test_counter_increments_after_all_retries_exhausted(self):
        """Verify audit_write_failures counter increments when all retries fail."""
        failing_session = AsyncMock()
        failing_session.commit = AsyncMock(side_effect=RuntimeError("db down"))
        failing_session.__aenter__ = AsyncMock(return_value=failing_session)
        failing_session.__aexit__ = AsyncMock(return_value=False)

        factory = MagicMock()
        factory.return_value = failing_session

        before = audit_write_failures._value.get()

        with patch("app.services.audit_service.asyncio.sleep", new_callable=AsyncMock):
            await write_audit_log_background(
                factory,
                request_id=str(uuid.uuid4()),
                action="CREATE_EVENT",
                entity_type="InvestmentEvent",
                entity_id=str(uuid.uuid4()),
                api_key_id="test_client",
                ip_address="127.0.0.1",
            )

        after = audit_write_failures._value.get()
        assert after == before + 1
