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

Interactive OpenAPI docs are available at `http://localhost:8000/docs` when the server is running.

### Authentication

All `/api/v1/*` endpoints require the `X-API-Key` header. Health checks are unauthenticated.

```
X-API-Key: your-raw-key
```

Generate an API key hash and add it to `.env`:

```bash
python3 -c "import hashlib; print(hashlib.sha256(b'your-raw-key').hexdigest())"
```

```
API_KEYS=client_name:sha256hash_here
```

Multiple keys are comma-separated: `client_a:hash_a,client_b:hash_b`.

Unauthorized requests return `401`:
```json
{ "detail": "Invalid or missing API key" }
```

### Rate Limits

| Endpoint group | Limit |
|---|---|
| Event ingestion (single) | 100 req/min |
| Event ingestion (batch) | 20 req/min |
| Event retrieval & analytics | 200 req/min |

---

### Event Ingestion

#### `POST /api/v1/events` — Ingest single event

Idempotent via `event_id`. Returns `201 Created` for new events, `200 OK` for duplicates.

**Request body:**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `event_id` | `uuid` | No | auto-generated | Idempotency key — reuse to deduplicate retries |
| `event_type` | `string` | Yes | — | One of: `ALLOCATION`, `REDEMPTION`, `TRANSFER`, `VALUATION_UPDATE` |
| `portfolio_id` | `uuid` | Yes | — | Portfolio identifier |
| `asset_id` | `string` | Yes | — | Asset identifier (1–20 chars, uppercase alphanumeric, e.g. `AAPL`, `SA1234`) |
| `asset_class` | `string` | Yes | — | One of: `PRIVATE_EQUITY`, `REAL_ESTATE`, `HEDGE_FUND`, `FIXED_INCOME`, `EQUITY` |
| `amount` | `decimal` | Yes | — | Transaction amount (must be > 0) |
| `currency` | `string` | No | `"SAR"` | ISO 4217 currency code (3 chars) |
| `fx_rate_to_sar` | `decimal` | No | `1.0` | FX conversion rate to SAR (must be > 0) |
| `created_at` | `datetime` | No | now | ISO 8601 with timezone. Must be within 30 days past to 5 minutes future |
| `metadata` | `object` | No | `null` | Arbitrary JSON (max 4096 bytes serialized) |
| `notes` | `string` | No | `null` | Free-text notes (max 1000 chars) |

**Example request:**
```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "X-API-Key: your-raw-key" \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "550e8400-e29b-41d4-a716-446655440000",
    "event_type": "ALLOCATION",
    "portfolio_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    "asset_id": "AAPL",
    "asset_class": "PRIVATE_EQUITY",
    "amount": "500000.00",
    "currency": "SAR",
    "fx_rate_to_sar": "1.0",
    "created_at": "2026-03-04T10:00:00Z",
    "metadata": { "deal_name": "STC Ventures Series B" }
  }'
```

**Response (201 Created):**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "ALLOCATION",
  "portfolio_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "asset_id": "AAPL",
  "asset_class": "PRIVATE_EQUITY",
  "amount": "500000.00",
  "currency": "SAR",
  "fx_rate_to_sar": "1.0",
  "amount_sar": "500000.00",
  "status": "PROCESSED",
  "created_at": "2026-03-04T10:00:00Z",
  "ingested_at": "2026-03-04T10:00:01Z",
  "processed_at": null,
  "metadata": { "deal_name": "STC Ventures Series B" },
  "notes": null
}
```

---

#### `POST /api/v1/events/batch` — Ingest batch of events

Accepts up to 100 events in a single request. Returns `207 Multi-Status`.

**Request body:**
```json
{
  "events": [ ...up to 100 EventCreate objects... ]
}
```

**Response (207 Multi-Status):**
```json
{
  "accepted": 8,
  "duplicates": 1,
  "failed": 1,
  "events": [ ...EventResponse objects... ]
}
```

---

#### `GET /api/v1/events/{event_id}` — Retrieve single event

Returns `200 OK` with the event, or `404 Not Found`.

**Example:**
```bash
curl http://localhost:8000/api/v1/events/550e8400-e29b-41d4-a716-446655440000 \
  -H "X-API-Key: your-raw-key"
```

---

### Analytics

All analytics responses include `cache_hit: bool` indicating whether the result was served from Redis.

#### `GET /api/v1/analytics/portfolio/{portfolio_id}/exposure`

AUM breakdown by asset class with allocation percentages.

**Response (200 OK):**
```json
{
  "portfolio_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "total_aum_sar": "1000000.00",
  "currency": "SAR",
  "exposures": [
    { "asset_class": "PRIVATE_EQUITY", "amount_sar": "600000.00", "allocation_pct": 60.0, "event_count": 3 },
    { "asset_class": "REAL_ESTATE", "amount_sar": "400000.00", "allocation_pct": 40.0, "event_count": 2 }
  ],
  "as_of": "2026-03-04T10:00:00Z",
  "cache_hit": false
}
```

---

#### `GET /api/v1/analytics/portfolio/{portfolio_id}/summary`

Total AUM with event type breakdown for a portfolio.

**Response (200 OK):**
```json
{
  "portfolio_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "total_aum_sar": "1000000.00",
  "total_events": 12,
  "allocations": 5,
  "redemptions": 2,
  "transfers": 3,
  "valuation_updates": 2,
  "last_event_at": "2026-03-04T10:00:00Z",
  "as_of": "2026-03-04T10:00:01Z",
  "cache_hit": false
}
```

---

#### `GET /api/v1/analytics/events` — Paginated event stream

Filterable, paginated list of events (not cached).

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `portfolio_id` | `uuid` | — | Filter by portfolio |
| `event_type` | `string` | — | Filter by event type |
| `asset_class` | `string` | — | Filter by asset class |
| `from_date` | `datetime` | — | Events after this date (ISO 8601) |
| `to_date` | `datetime` | — | Events before this date (ISO 8601) |
| `page` | `int` | `1` | Page number (≥ 1) |
| `page_size` | `int` | `50` | Results per page (1–200) |

**Example:**
```bash
curl "http://localhost:8000/api/v1/analytics/events?portfolio_id=6ba7b810-9dad-11d1-80b4-00c04fd430c8&event_type=ALLOCATION&page=1&page_size=20" \
  -H "X-API-Key: your-raw-key"
```

**Response (200 OK):**
```json
{
  "total": 45,
  "page": 1,
  "page_size": 20,
  "events": [
    {
      "event_id": "550e8400-e29b-41d4-a716-446655440000",
      "event_type": "ALLOCATION",
      "portfolio_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      "asset_class": "PRIVATE_EQUITY",
      "amount_sar": "500000.00",
      "currency": "SAR",
      "created_at": "2026-03-04T10:00:00Z",
      "ingested_at": "2026-03-04T10:00:01Z"
    }
  ]
}
```

---

#### `GET /api/v1/analytics/aggregate` — Global aggregate

Global AUM and asset class breakdown across all portfolios.

**Response (200 OK):**
```json
{
  "total_aum_sar": "15000000.00",
  "total_portfolios": 12,
  "total_events": 340,
  "exposures_by_asset_class": [
    { "asset_class": "PRIVATE_EQUITY", "amount_sar": "6000000.00", "allocation_pct": 40.0, "event_count": 120 },
    { "asset_class": "REAL_ESTATE", "amount_sar": "4500000.00", "allocation_pct": 30.0, "event_count": 80 }
  ],
  "as_of": "2026-03-04T10:00:01Z",
  "cache_hit": true
}
```

---

### System

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | `GET` | No | Liveness probe — always returns `200` |
| `/health/ready` | `GET` | No | Readiness probe — returns `200` if DB + Redis are healthy, `503` if degraded |

**Readiness response:**
```json
{ "status": "ready", "database": "ok", "cache": "ok" }
```

---

### Enums

**Event Types:** `ALLOCATION` · `REDEMPTION` · `TRANSFER` · `VALUATION_UPDATE`

**Asset Classes:** `PRIVATE_EQUITY` · `REAL_ESTATE` · `HEDGE_FUND` · `FIXED_INCOME` · `EQUITY`

**Event Statuses:** `PENDING` · `PROCESSED` · `FAILED`

---

### Error Responses

All errors follow a consistent format:

| Status | Condition |
|---|---|
| `401 Unauthorized` | Missing or invalid `X-API-Key` |
| `404 Not Found` | Event ID does not exist |
| `422 Unprocessable Entity` | Validation error (invalid fields, batch exceeds 100) |
| `429 Too Many Requests` | Rate limit exceeded |

**Validation error example:**
```json
{
  "detail": [
    {
      "loc": ["body", "amount"],
      "msg": "Input should be greater than 0",
      "type": "greater_than"
    }
  ]
}
```

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
6. **Offset-based pagination**: The `GET /analytics/events` endpoint uses offset pagination, which degrades on deep pages (>100K events). For large datasets, cursor-based pagination (keyset on `created_at` + `event_id`) would provide consistent O(1) page fetches.
7. **Aggregation-based analytics**: Analytics are computed via SQL `GROUP BY` rather than event sourcing / CQRS. This is simpler to implement and sufficient for the case study scope. A production CMA-compliant system may benefit from event sourcing for full auditability and point-in-time portfolio reconstruction.

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
