"""Unit tests for the rate limiting module."""

from unittest.mock import MagicMock

from app.core.rate_limit import _key_func
from app.core.security import hash_api_key


class TestKeyFunc:
    def test_returns_hashed_api_key_when_present(self):
        """When X-API-Key header is present, the key function returns its hash."""
        raw_key = "test-api-key-12345"
        request = MagicMock()
        request.headers = {"X-API-Key": raw_key}

        result = _key_func(request)
        assert result == hash_api_key(raw_key)
        # Must NOT return the raw key
        assert result != raw_key

    def test_returns_ip_when_no_api_key(self):
        """When no API key is present, falls back to remote address."""
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "192.168.1.100"

        result = _key_func(request)
        assert result == "192.168.1.100"

    def test_different_keys_produce_different_hashes(self):
        """Different API keys must produce distinct rate-limit keys."""
        request_a = MagicMock()
        request_a.headers = {"X-API-Key": "key-a"}

        request_b = MagicMock()
        request_b.headers = {"X-API-Key": "key-b"}

        assert _key_func(request_a) != _key_func(request_b)

    def test_same_key_produces_same_hash(self):
        """Deterministic: the same raw key always maps to the same limiter key."""
        request_1 = MagicMock()
        request_1.headers = {"X-API-Key": "my-key"}

        request_2 = MagicMock()
        request_2.headers = {"X-API-Key": "my-key"}

        assert _key_func(request_1) == _key_func(request_2)
