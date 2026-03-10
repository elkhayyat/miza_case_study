import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import (
    GLOBAL_AGGREGATE_KEY,
    cache_delete_many,
    portfolio_exposure_key,
    portfolio_summary_key,
)
from app.core.logging import get_logger
from app.models.event import EventStatus, EventType, InvestmentEvent
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
    try:
        async with db.begin_nested():
            db.add(event)
            await db.flush()
    except IntegrityError:
        # Concurrent duplicate — savepoint rolled back, re-fetch the winning row
        existing = await get_event_by_id(db, data.event_id)
        if existing is not None:
            return existing, True
        raise

    # Invalidate cached analytics for this portfolio
    pid = str(event.portfolio_id)
    await cache_delete_many(
        [
            portfolio_exposure_key(pid),
            portfolio_summary_key(pid),
            GLOBAL_AGGREGATE_KEY,
        ]
    )

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
            # Concurrent duplicate — re-fetch before counting as failed
            existing_dup = await get_event_by_id(db, data.event_id)
            if existing_dup is not None:
                duplicate_count += 1
                processed.append(existing_dup)
            else:
                logger.warning("Data integrity violation for event_id=%s, skipping", data.event_id)
                failed_count += 1
        except Exception:
            logger.exception("Unexpected error ingesting event_id=%s", data.event_id)
            failed_count += 1

    if invalidated_portfolios:
        keys = [GLOBAL_AGGREGATE_KEY]
        for pid in invalidated_portfolios:
            keys.append(portfolio_exposure_key(pid))
            keys.append(portfolio_summary_key(pid))
        await cache_delete_many(keys)

    return processed, duplicate_count, failed_count


def amount_sar_expr() -> ColumnElement[Any]:
    """SQL expression: signed amount * fx_rate_to_sar.

    REDEMPTION events are negative (subtract from AUM); all other event types
    (ALLOCATION, TRANSFER, VALUATION_UPDATE) are positive.
    """
    signed = case(
        (InvestmentEvent.event_type == EventType.REDEMPTION, -InvestmentEvent.amount),
        else_=InvestmentEvent.amount,
    )
    return signed * InvestmentEvent.fx_rate_to_sar


def compute_amount_sar(event: InvestmentEvent) -> Decimal:
    """Python-level equivalent of ``amount_sar_expr``."""
    sign = Decimal("-1") if event.event_type == EventType.REDEMPTION else Decimal("1")
    return sign * event.amount * event.fx_rate_to_sar
