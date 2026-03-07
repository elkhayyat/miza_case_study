"""Unit tests for API key authentication."""

import hashlib

from app.core.security import hash_api_key


class TestHashApiKey:
    def test_returns_sha256_hex(self):
        raw = "my-secret-key"
        result = hash_api_key(raw)
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert result == expected

    def test_deterministic(self):
        raw = "test-key"
        assert hash_api_key(raw) == hash_api_key(raw)

    def test_different_keys_different_hashes(self):
        assert hash_api_key("key-a") != hash_api_key("key-b")

    def test_output_is_64_chars(self):
        result = hash_api_key("any-key")
        assert len(result) == 64

    def test_empty_string_handled(self):
        result = hash_api_key("")
        assert len(result) == 64
