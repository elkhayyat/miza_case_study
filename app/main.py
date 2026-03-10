import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from starlette.responses import Response

from app.api.v1.router import api_router
from app.cache.redis_client import close_redis, get_redis
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger, set_request_id
from app.core.metrics import rate_limit_hits
from app.core.rate_limit import get_limiter
from app.core.tracing import setup_tracing

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info(
        "Starting %s v%s [%s]",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )

    setup_tracing(app)

    # Warm up Redis connection
    try:
        await get_redis().ping()
        logger.info("Redis connection established")
    except Exception as exc:
        logger.warning("Redis not available on startup: %s", exc)

    yield

    await close_redis()
    logger.info("Shutdown complete")


def _rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """Custom rate-limit handler that increments the Prometheus counter."""
    api_key = request.headers.get("X-API-Key")
    key_type = "api_key" if api_key else "ip"
    rate_limit_hits.labels(key_type=key_type).inc()
    detail = getattr(exc, "detail", str(exc))
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {detail}"},
    )


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Miza Investment Analytics API",
        description=(
            "Real-Time Investment Event Analytics Microservice for Miza Capital. "
            "Supports high-concurrency event ingestion, portfolio analytics, "
            "and CMA-compliant audit logging."
        ),
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "X-Request-ID", "Content-Type"],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[..., Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        set_request_id(request_id)

        from opentelemetry import trace

        trace.get_current_span().set_attribute("request.id", request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception(
            "Unhandled %s on %s %s [request_id=%s]",
            type(exc).__name__,
            request.method,
            request.url.path,
            request_id,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )

    limiter = get_limiter()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(api_router)

    # Prometheus instrumentation — auto-tracks HTTP request duration/count/active
    Instrumentator(
        excluded_handlers=["/health", "/health/ready", "/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics")

    return app


app = create_app()
