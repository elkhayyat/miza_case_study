"""Unit tests for the audit service."""

import uuid

from app.services.audit_service import compute_payload_hash, write_audit_log


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
