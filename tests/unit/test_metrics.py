"""Unit tests for Prometheus business metrics."""

from app.core.metrics import (
    audit_write_failures,
    cache_operations,
    event_ingestion,
    rate_limit_hits,
)


def _counter_value(counter, labels: dict) -> float:
    """Get the current value of a labelled counter from the registry."""
    return counter.labels(**labels)._value.get()


class TestCacheMetrics:
    def test_cache_hit_increments(self):
        before = _counter_value(cache_operations, {"operation": "get", "result": "hit"})
        cache_operations.labels(operation="get", result="hit").inc()
        after = _counter_value(cache_operations, {"operation": "get", "result": "hit"})
        assert after == before + 1

    def test_cache_miss_increments(self):
        before = _counter_value(cache_operations, {"operation": "get", "result": "miss"})
        cache_operations.labels(operation="get", result="miss").inc()
        after = _counter_value(cache_operations, {"operation": "get", "result": "miss"})
        assert after == before + 1


class TestEventIngestionMetrics:
    def test_accepted_increments(self):
        before = _counter_value(event_ingestion, {"status": "accepted"})
        event_ingestion.labels(status="accepted").inc()
        after = _counter_value(event_ingestion, {"status": "accepted"})
        assert after == before + 1

    def test_duplicate_increments(self):
        before = _counter_value(event_ingestion, {"status": "duplicate"})
        event_ingestion.labels(status="duplicate").inc()
        after = _counter_value(event_ingestion, {"status": "duplicate"})
        assert after == before + 1


class TestRateLimitMetrics:
    def test_rate_limit_counter_increments(self):
        before = _counter_value(rate_limit_hits, {"key_type": "ip"})
        rate_limit_hits.labels(key_type="ip").inc()
        after = _counter_value(rate_limit_hits, {"key_type": "ip"})
        assert after == before + 1


class TestAuditWriteFailures:
    def test_audit_write_failures_increments(self):
        before = audit_write_failures._value.get()
        audit_write_failures.inc()
        after = audit_write_failures._value.get()
        assert after == before + 1
