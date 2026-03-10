# Miza Investment Analytics — Real-Time Microservice

A production-grade Python microservice for real-time investment event ingestion and portfolio analytics, built as part of the Miza Capital Head of Engineering case study.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Layer                                │
│  FastAPI (async) · Pydantic v2 validation · API Key Auth        │
└────────────────────────────┬────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
   Event Ingestion    Analytics Engine    Audit Service
   (idempotent)       (cache-aside)       (append-only)
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐
│   PostgreSQL    │  │    Redis     │  │   PostgreSQL     │
│  (ACID, events)│  │  (30s TTL)   │  │  (audit_logs)    │
└─────────────────┘  └──────────────┘  └──────────────────┘
```

**Tech stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 async · asyncpg · Alembic · Redis · Pydantic v2 · Docker · GitHub Actions

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- (For local dev) Python 3.12 + [uv](https://docs.astral.sh/uv/)

### Run with Docker

```bash
# 1. Clone and configure
cp .env.example .env

# 2. Start all services (Postgres, Redis, migrations, API)
docker compose up --build

# 3. Verify health
curl http://localhost:8000/health/ready
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Local Development

```bash
# Install dependencies (uv recommended)
uv sync --group dev

# Start infrastructure
docker compose up postgres redis -d

# Run migrations
uv run alembic upgrade head

# Start the API server
uv run uvicorn app.main:app --reload

# Run tests
uv run pytest tests/
```

---

## API Reference

All endpoints require the `X-API-Key` header.

### Authentication

Generate an API key hash:
```bash
python3 -c "import hashlib; print(hashlib.sha256(b'your-raw-key').hexdigest())"
```

Add to `.env`:
```
API_KEYS=client_name:sha256hash_here
```

### Event Ingestion

#### `POST /api/v1/events`
Ingest a single investment event. Idempotent via `event_id`.

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "ALLOCATION",
  "portfolio_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "asset_id": "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
  "asset_class": "PRIVATE_EQUITY",
  "amount": "500000.00",
  "currency": "SAR",
  "fx_rate_to_sar": "1.0",
  "created_at": "2026-03-04T10:00:00Z",
  "metadata": { "deal_name": "STC Ventures Series B" }
}
```

Returns `201` for new events, `200` for duplicates.

#### `POST /api/v1/events/batch`
Ingest up to 100 events in a single request. Returns `207 Multi-Status`.

```json
{ "events": [ ...up to 100 event objects... ] }
```

#### `GET /api/v1/events/{event_id}`
Retrieve a single event by ID. Returns `404` if not found.

### Analytics

#### `GET /api/v1/analytics/portfolio/{portfolio_id}/exposure`
AUM breakdown by asset class with allocation percentages.

```json
{
  "portfolio_id": "...",
  "total_aum_sar": "1000000.00",
  "currency": "SAR",
  "exposures": [
    { "asset_class": "PRIVATE_EQUITY", "amount_sar": "600000", "allocation_pct": 60.0, "event_count": 3 },
    { "asset_class": "REAL_ESTATE", "amount_sar": "400000", "allocation_pct": 40.0, "event_count": 2 }
  ],
  "as_of": "2026-03-04T10:00:00Z",
  "cache_hit": false
}
```

#### `GET /api/v1/analytics/portfolio/{portfolio_id}/summary`
Total AUM and event type counts for a portfolio.

#### `GET /api/v1/analytics/events`
Paginated event stream with filters:
- `portfolio_id`, `event_type`, `asset_class`
- `from_date`, `to_date` (ISO 8601)
- `page`, `page_size` (max 200)

#### `GET /api/v1/analytics/aggregate`
Global AUM and exposure across all portfolios.

### System

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness probe — always `200` |
| `GET /health/ready` | Readiness probe — checks DB + Redis |

### Event Types
`ALLOCATION` · `REDEMPTION` · `TRANSFER` · `VALUATION_UPDATE`

### Asset Classes
`PRIVATE_EQUITY` · `REAL_ESTATE` · `HEDGE_FUND` · `FIXED_INCOME` · `EQUITY`

---

## Architecture Decisions

### 1. FastAPI + asyncpg for Concurrency
The full async stack (HTTP → service layer → DB driver) allows a single process to handle thousands of concurrent connections without blocking. asyncpg is the fastest Python PostgreSQL driver. Connection pools are tunable via environment variables (default: 5–20 connections). This directly addresses the 1,000+ concurrent users requirement.

### 2. Cache-aside with Redis (sub-500ms target)
Analytics reads check Redis first (30-second TTL). Cache is invalidated on event ingestion for the affected portfolio. On cache miss, the DB query returns in ~5–20ms due to composite indexes. On cache hit, responses are ~1ms — well under the 500ms SLA.

### 3. Idempotency via client-supplied `event_id`
Financial systems commonly retry on failure. Rather than generating server-side IDs, the client supplies a UUID that acts as an idempotency key. Re-submitting the same `event_id` returns the existing record without error. This is critical for reliable event ingestion during high-traffic windows.

### 4. Immutable Audit Log
The `audit_logs` table is append-only by design — no UPDATE or DELETE operations are ever issued against it. Every API call (read and write) creates an audit record with: request correlation ID, API key attribution, SHA-256 hash of the request payload (integrity verification), and IP address. This architecture supports CMA audit requirements and SIEM integration via structured JSON logs.

### 5. API Key Authentication
API keys are stored as SHA-256 hashes in environment configuration — never plaintext. Each key carries a `client_id` for audit attribution. This approach is simple to operate for B2B/B2C scenarios and straightforward to extend to a database-backed key management system.

### 6. Multi-stage Dockerfile
The builder stage installs dependencies; the runtime stage copies only the virtual environment and application code, producing a ~150MB image. The runtime uses a non-root user (`miza` uid 1001) for security.

---

## Scalability Approach

| Challenge | Solution |
|---|---|
| 1,000+ concurrent users | Async FastAPI + asyncpg connection pool (non-blocking I/O) |
| Sub-500ms analytics | Redis cache-aside with 30s TTL + indexed DB queries |
| High-volume event ingestion | Batch endpoint (up to 100 events/request), background audit writes |
| Database hotspots | Composite indexes on `(portfolio_id, asset_class)` and `created_at` |
| Horizontal scale | Stateless API containers — add instances behind a load balancer |
| Cache stampede | Short TTL + background invalidation limits stale reads |

**Horizontal scaling**: The API service is fully stateless. Scale by increasing the `--workers` flag in uvicorn or deploying multiple container replicas behind a load balancer. Redis and PostgreSQL are shared resources and scale independently.

---

## Production Readiness Considerations

- **Secrets management**: Replace env-var API keys with HashiCorp Vault or AWS Secrets Manager
- **Database connection pooling**: PgBouncer in front of PostgreSQL for 10,000+ connection support
- **Observability**: Structured JSON logs are SIEM-compatible; add OpenTelemetry for distributed tracing
- **Rate limiting**: Per-client rate limits enforced via slowapi — ingestion at 100 req/min, batch at 20 req/min, reads at 200 req/min
- **TLS termination**: Place an nginx/ALB in front of the service in production
- **Backup and recovery**: Continuous WAL archiving for PostgreSQL; Redis persistence with AOF
- **Migration safety**: All Alembic migrations include `downgrade()` for rollback capability
- **Health checks**: Both liveness and readiness probes are implemented for Kubernetes compatibility

---

## Assumptions and Trade-offs

| Assumption | Impact |
|---|---|
| `amount` in events is always positive | REDEMPTION events are subtracted from AUM via sign logic in the analytics engine; a full double-entry ledger would track debits/credits separately |
| FX rates are supplied by the client | No real-time FX feed integration — caller is responsible for accurate rates |
| API keys are long-lived | No token expiry or rotation — production would need TTL + rotation |
| Single-region deployment | No cross-region replication for Redis or PostgreSQL |
| Analytics are eventually consistent | Cache TTL means analytics may lag ingestion by up to 30 seconds |

---

## Known Limitations

1. **No real-time streaming**: Analytics are computed on demand (request-response). A WebSocket or SSE endpoint for live portfolio updates would require a message broker (e.g., Kafka).
2. **No currency FX feed**: FX rates are caller-supplied. Production would integrate a live rates feed.
3. **Simple API key auth**: No OAuth2, JWT, or MFA. Sufficient for B2B service auth but not end-user auth.
4. **Audit log retention**: No archival or TTL policy on `audit_logs`. A production CMA-compliant system needs a defined retention period.
5. **Single-region**: No active-active failover. RTO/RPO would need definition based on CMA requirements.

---

## CI/CD Pipeline

GitHub Actions runs on every push and pull request:

```
lint (ruff + mypy) → test (SQLite) + test (PostgreSQL) → docker build + push
```

Docker images are tagged:
- `sha-<short-git-sha>` — every build
- `latest` — main branch only
- Branch name — feature branches

Images are pushed to GitHub Container Registry on main branch merges.

---

## Project Structure

```
app/
├── api/v1/endpoints/   # FastAPI route handlers
├── core/               # Config, logging, security
├── db/                 # SQLAlchemy engine and session
├── models/             # ORM models (InvestmentEvent, AuditLog)
├── schemas/            # Pydantic request/response schemas
├── services/           # Business logic (event, analytics, audit)
├── cache/              # Redis client and cache helpers
└── main.py             # FastAPI app factory

tests/
├── unit/               # Service and schema unit tests
├── integration/        # Full API tests with SQLite test DB
└── conftest.py         # Shared fixtures

alembic/                # Database migration scripts
.github/workflows/      # GitHub Actions CI/CD
```
