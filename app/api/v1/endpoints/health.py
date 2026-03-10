from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.cache.redis_client import check_redis_health
from app.db.session import get_engine

router = APIRouter()


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    cache: str


@router.get("/health", response_model=HealthResponse, tags=["System"])
async def liveness() -> HealthResponse:
    """Liveness probe — always returns 200 if the process is running."""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=ReadinessResponse, tags=["System"])
async def readiness() -> ReadinessResponse | JSONResponse:
    """Readiness probe — checks DB and Redis connectivity."""
    db_status = "ok"
    cache_status = "ok"

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    cache_ok = await check_redis_health()
    if not cache_ok:
        cache_status = "error"

    is_ready = db_status == "ok" and cache_status == "ok"
    overall = "ready" if is_ready else "degraded"
    result = ReadinessResponse(status=overall, database=db_status, cache=cache_status)
    status_code = 200 if is_ready else 503
    return JSONResponse(content=result.model_dump(), status_code=status_code)
