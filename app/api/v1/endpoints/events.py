import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.metrics import event_ingestion
from app.core.rate_limit import get_limiter
from app.core.security import APIKeyInfo, require_api_key
from app.db.session import get_db, get_session_factory
from app.models.event import InvestmentEvent
from app.schemas.event import BatchEventResponse, EventBatchCreate, EventCreate, EventResponse
from app.services import audit_service, event_service

router = APIRouter()
limiter = get_limiter()


def _event_to_response(event: InvestmentEvent) -> EventResponse:
    # Decimal(str()) ensures consistent types: asyncpg returns Decimal natively,
    # but aiosqlite (used in tests) returns float for Numeric columns.
    return EventResponse(
        event_id=event.event_id,
        event_type=event.event_type,
        portfolio_id=event.portfolio_id,
        asset_id=event.asset_id,
        asset_class=event.asset_class,
        amount=Decimal(str(event.amount)),
        currency=event.currency,
        fx_rate_to_sar=Decimal(str(event.fx_rate_to_sar)),
        amount_sar=event_service.compute_amount_sar(event),
        status=event.status,
        created_at=event.created_at,
        ingested_at=event.ingested_at,
        processed_at=event.processed_at,
        metadata=event.metadata_,
        notes=event.notes,
    )


@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Events"],
    summary="Ingest a single investment event",
)
@limiter.limit("100/minute")
async def ingest_event(
    request: Request,
    data: EventCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    api_key: Annotated[APIKeyInfo, Depends(require_api_key)],
) -> EventResponse | JSONResponse:
    request_id = request.state.request_id
    client_ip = request.client.host if request.client else "unknown"

    event, is_duplicate = await event_service.ingest_event(db, data)
    event_ingestion.labels(status="duplicate" if is_duplicate else "accepted").inc()

    await audit_service.write_audit_log(
        db,
        request_id=request_id,
        action="CREATE_EVENT",
        entity_type="InvestmentEvent",
        entity_id=str(event.event_id),
        api_key_id=api_key.client_id,
        ip_address=client_ip,
        payload={"event_id": str(data.event_id), "duplicate": is_duplicate},
    )

    if is_duplicate:
        response = _event_to_response(event)
        return JSONResponse(
            content=response.model_dump(mode="json"),
            status_code=status.HTTP_200_OK,
        )

    return _event_to_response(event)


@router.post(
    "/events/batch",
    response_model=BatchEventResponse,
    status_code=status.HTTP_207_MULTI_STATUS,
    tags=["Events"],
    summary="Ingest a batch of investment events (max 100)",
)
@limiter.limit("20/minute")
async def ingest_batch(
    request: Request,
    data: EventBatchCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    api_key: Annotated[APIKeyInfo, Depends(require_api_key)],
) -> BatchEventResponse:
    settings = get_settings()
    if len(data.events) > settings.max_batch_size:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Batch size {len(data.events)} exceeds maximum of {settings.max_batch_size}",
        )

    request_id = request.state.request_id
    client_ip = request.client.host if request.client else "unknown"

    events, duplicates, failed = await event_service.ingest_batch(db, data.events)
    accepted = len(events) - duplicates - failed
    event_ingestion.labels(status="accepted").inc(accepted)
    event_ingestion.labels(status="duplicate").inc(duplicates)
    event_ingestion.labels(status="failed").inc(failed)

    await audit_service.write_audit_log(
        db,
        request_id=request_id,
        action="CREATE_BATCH_EVENTS",
        entity_type="InvestmentEvent",
        entity_id=None,
        api_key_id=api_key.client_id,
        ip_address=client_ip,
        payload={
            "submitted": len(data.events),
            "accepted": accepted,
            "duplicates": duplicates,
            "failed": failed,
        },
    )

    return BatchEventResponse(
        accepted=accepted,
        duplicates=duplicates,
        failed=failed,
        events=[_event_to_response(e) for e in events],
    )


@router.get(
    "/events/{event_id}",
    response_model=EventResponse,
    tags=["Events"],
    summary="Retrieve a single event by ID",
)
@limiter.limit("200/minute")
async def get_event(
    event_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    api_key: Annotated[APIKeyInfo, Depends(require_api_key)],
) -> EventResponse:
    event = await event_service.get_event_by_id(db, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    background_tasks.add_task(
        audit_service.write_audit_log_background,
        session_factory=get_session_factory(),
        request_id=request.state.request_id,
        action="READ_EVENT",
        entity_type="InvestmentEvent",
        entity_id=str(event_id),
        api_key_id=api_key.client_id,
        ip_address=request.client.host if request.client else "unknown",
    )
    return _event_to_response(event)
