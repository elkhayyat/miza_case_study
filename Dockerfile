# ──────────────────────────────────────────────
# Stage 1: builder — install dependencies
# ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Use /app so venv shebangs match the runtime stage path
WORKDIR /app

# Install uv (pinned version)
COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install production deps using lockfile
RUN uv sync --frozen --no-dev

# ──────────────────────────────────────────────
# Stage 2: runtime — minimal image
# ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Non-root user for security
RUN groupadd --gid 1001 miza && \
    useradd --uid 1001 --gid miza --shell /bin/sh --create-home miza

# Copy virtual environment from builder (paths match — shebangs are correct)
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Default 4 workers suits 2-core containers (2x CPU cores).
# Override at runtime: docker run -e WEB_CONCURRENCY=8
# Each worker holds its own DB connection pool (default 5-20 connections).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app" \
    WEB_CONCURRENCY=4

USER miza

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY}
