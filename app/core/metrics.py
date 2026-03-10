"""Prometheus business metrics for Miza Analytics."""

from prometheus_client import Counter

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

audit_write_failures = Counter(
    "miza_audit_write_failures_total",
    "Audit log writes that failed after all retries",
)
