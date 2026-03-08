import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import cache_delete_pattern
from app.core.logging import get_logger
from app.models.event import EventStatus, InvestmentEvent
from app.schemas.event import EventCreate

logger = get_logger(__name__)


async def get_event_by_id(db: AsyncSession, event_id: uuid.UUID) -> InvestmentEvent | None:
    result = await db.execute(select(InvestmentEvent).where(InvestmentEvent.event_id == event_id))
    return result.scalar_one_or_none()


async def _get_existing_event_ids(
    db: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, InvestmentEvent]:
    """Batch-check for existing events by IDs."""
    if not event_ids:
        return {}
    result = await db.execute(
        select(InvestmentEvent).where(InvestmentEvent.event_id.in_(event_ids))
    )
    return {e.event_id: e for e in result.scalars().all()}


def _build_event(data: EventCreate) -> InvestmentEvent:
    now = datetime.now(UTC)
    return InvestmentEvent(
        event_id=data.event_id,
        event_type=data.event_type,
        portfolio_id=data.portfolio_id,
        asset_id=data.asset_id,
        asset_class=data.asset_class,
        amount=data.amount,
        currency=data.currency,
        fx_rate_to_sar=data.fx_rate_to_sar,
        metadata_=data.metadata,
        notes=data.notes,
        status=EventStatus.PROCESSED,
        created_at=data.created_at,
        ingested_at=now,
        processed_at=now,
    )


async def ingest_event(
    db: AsyncSession,
    data: EventCreate,
) -> tuple[InvestmentEvent, bool]:
    """
    Ingest a single event. Returns (event, is_duplicate).
    Idempotent: re-submitting the same event_id returns the existing record.
    """
    existing = await get_event_by_id(db, data.event_id)
    if existing is not None:
        return existing, True

    event = _build_event(data)
    db.add(event)
    await db.flush()

    # Invalidate cached analytics for this portfolio
    await cache_delete_pattern(f"analytics:portfolio:{event.portfolio_id}:*")
    await cache_delete_pattern("analytics:global:*")

    return event, False


async def ingest_batch(
    db: AsyncSession,
    events_data: list[EventCreate],
) -> tuple[list[InvestmentEvent], int, int]:
    """
    Ingest a batch of events.
    Returns (processed_events, duplicate_count, failed_count).
    """
    processed: list[InvestmentEvent] = []
    duplicate_count = 0
    failed_count = 0
    invalidated_portfolios: set[str] = set()

    # Batch dedup check
    all_ids = [d.event_id for d in events_data]
    existing_map = await _get_existing_event_ids(db, all_ids)

    for data in events_data:
        existing = existing_map.get(data.event_id)
        if existing is not None:
            duplicate_count += 1
            processed.append(existing)
            continue

        try:
            event = _build_event(data)
            async with db.begin_nested():
                db.add(event)
                await db.flush()
            processed.append(event)
            invalidated_portfolios.add(str(event.portfolio_id))
        except IntegrityError:
            logger.warning("Data integrity violation for event_id=%s, skipping", data.event_id)
            failed_count += 1
        except Exception:
            logger.exception("Unexpected error ingesting event_id=%s", data.event_id)
            failed_count += 1

    for portfolio_id in invalidated_portfolios:
        await cache_delete_pattern(f"analytics:portfolio:{portfolio_id}:*")
    if invalidated_portfolios:
        await cache_delete_pattern("analytics:global:*")

    return processed, duplicate_count, failed_count


def amount_sar_expr() -> ColumnElement[Any]:
    """SQL expression for amount * fx_rate_to_sar (for use in queries).

    This is the SQL-level equivalent of ``compute_amount_sar`` for in-memory
    computation.
    """
    return InvestmentEvent.amount * InvestmentEvent.fx_rate_to_sar


def compute_amount_sar(event: InvestmentEvent) -> Decimal:
    """Python-level equivalent of ``amount_sar_expr`` for in-memory objects."""
    return event.amount * event.fx_rate_to_sar
