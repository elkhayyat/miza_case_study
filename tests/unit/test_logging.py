"""Unit tests for the logging configuration module."""

import logging

from app.core.logging import configure_logging, get_logger


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
