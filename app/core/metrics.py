"""Prometheus business metrics for Miza Analytics."""

from prometheus_client import Counter, Histogram

cache_operations = Counter(
    "miza_cache_operations_total",
    "Cache operation outcomes",
    ["operation", "result"],
)

event_ingestion = Counter(
    "miza_event_ingestion_total",
    "Event ingestion outcomes",
    ["status"],
)

rate_limit_hits = Counter(
    "miza_rate_limit_hits_total",
    "Rate-limit rejections by key type",
    ["key_type"],
)

db_query_duration = Histogram(
    "miza_db_query_duration_seconds",
    "Database query latency",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

audit_write_failures = Counter(
    "miza_audit_write_failures_total",
    "Audit log writes that failed after all retries",
)
