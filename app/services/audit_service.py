import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.audit_log import AuditLog

logger = get_logger(__name__)

MAX_AUDIT_RETRIES = 3


def compute_payload_hash(payload: dict | None) -> str | None:
    if payload is None:
        return None
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


async def write_audit_log(
    db: AsyncSession,
    *,
    request_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    api_key_id: str,
    ip_address: str,
    payload: dict | None = None,
) -> AuditLog:
    """Append an immutable audit record. Never updates or deletes."""
    log = AuditLog(
        log_id=uuid.uuid4(),
        request_id=request_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        api_key_id=api_key_id,
        payload_hash=compute_payload_hash(payload),
        ip_address=ip_address,
        timestamp=datetime.now(UTC),
    )
    db.add(log)
    await db.flush()
    return log


async def write_audit_log_background(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    request_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    api_key_id: str,
    ip_address: str,
    payload: dict | None = None,
) -> None:
    """Write audit log in a background task with retry logic."""
    payload_hash = compute_payload_hash(payload)

    for attempt in range(1, MAX_AUDIT_RETRIES + 1):
        try:
            async with session_factory() as session:
                log = AuditLog(
                    log_id=uuid.uuid4(),
                    request_id=request_id,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    api_key_id=api_key_id,
                    payload_hash=payload_hash,
                    ip_address=ip_address,
                    timestamp=datetime.now(UTC),
                )
                session.add(log)
                await session.commit()
            return
        except Exception:
            if attempt == MAX_AUDIT_RETRIES:
                logger.exception(
                    "Failed to write audit log after %d attempts for request_id=%s",
                    MAX_AUDIT_RETRIES,
                    request_id,
                )
            else:
                delay = 0.1 * (2 ** (attempt - 1))
                logger.warning(
                    "Audit log attempt %d/%d failed for request_id=%s, retrying in %.1fs",
                    attempt,
                    MAX_AUDIT_RETRIES,
                    request_id,
                    delay,
                )
                await asyncio.sleep(delay)
