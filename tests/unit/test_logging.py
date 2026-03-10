"""Unit tests for the logging configuration module."""

import logging

from app.core.logging import (
    RequestIdFilter,
    configure_logging,
    get_logger,
    get_request_id,
    set_request_id,
)


class TestGetLogger:
    def test_returns_logger_instance(self):
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)

    def test_logger_has_correct_name(self):
        logger = get_logger("my.custom.name")
        assert logger.name == "my.custom.name"

    def test_same_name_returns_same_logger(self):
        logger1 = get_logger("shared.name")
        logger2 = get_logger("shared.name")
        assert logger1 is logger2


class TestConfigureLogging:
    def test_configures_root_logger(self):
        configure_logging()
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_json_formatter_attached(self):
        configure_logging()
        root = logging.getLogger()
        handler = root.handlers[0]
        assert handler.formatter is not None
        # Verify it's the JSON formatter
        formatter_class = type(handler.formatter).__name__
        assert "Json" in formatter_class or "json" in formatter_class.lower()

    def test_uvicorn_access_quieted(self):
        configure_logging()
        uvicorn_logger = logging.getLogger("uvicorn.access")
        assert uvicorn_logger.level >= logging.WARNING

    def test_respects_log_level_setting(self, monkeypatch):
        """Ensure configure_logging sets root level from settings."""
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        from app.core.config import get_settings

        get_settings.cache_clear()
        try:
            configure_logging()
            root = logging.getLogger()
            assert root.level == logging.DEBUG
        finally:
            monkeypatch.setenv("LOG_LEVEL", "INFO")
            get_settings.cache_clear()
            configure_logging()

    def test_configure_logging_adds_filter(self):
        """configure_logging attaches a RequestIdFilter to the root handler."""
        configure_logging()
        root = logging.getLogger()
        handler = root.handlers[0]
        filter_types = [type(f) for f in handler.filters]
        assert RequestIdFilter in filter_types


class TestRequestIdContextVar:
    def test_default_is_empty_string(self):
        set_request_id("")
        assert get_request_id() == ""

    def test_set_and_get_request_id(self):
        set_request_id("req-abc-123")
        assert get_request_id() == "req-abc-123"
        set_request_id("")


class TestRequestIdFilter:
    def test_filter_injects_request_id(self):
        set_request_id("req-filter-test")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=None,
            exc_info=None,
        )
        f = RequestIdFilter()
        result = f.filter(record)

        assert result is True
        assert record.request_id == "req-filter-test"  # type: ignore[attr-defined]
        set_request_id("")
