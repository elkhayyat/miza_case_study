"""Unit tests for OpenTelemetry tracing setup."""

from unittest.mock import MagicMock, patch

from app.core.tracing import get_tracer, setup_sqlalchemy_tracing, setup_tracing


class TestSetupTracing:
    def test_disabled_returns_none(self):
        """When otel_enabled=False, setup_tracing returns None (no-op)."""
        app = MagicMock()
        with patch("app.core.tracing.get_settings") as mock_settings:
            mock_settings.return_value.otel_enabled = False
            result = setup_tracing(app)
        assert result is None

    def test_enabled_returns_tracer_provider(self):
        """When otel_enabled=True, setup_tracing returns a TracerProvider."""
        app = MagicMock()
        with patch("app.core.tracing.get_settings") as mock_settings:
            mock_settings.return_value.otel_enabled = True
            mock_settings.return_value.otel_service_name = "test-svc"
            mock_settings.return_value.otel_exporter_endpoint = ""
            mock_settings.return_value.otel_exporter_insecure = True
            result = setup_tracing(app)

        from opentelemetry.sdk.trace import TracerProvider

        assert isinstance(result, TracerProvider)


class TestGetTracer:
    def test_get_tracer_returns_tracer(self):
        """get_tracer should return a valid tracer object."""
        tracer = get_tracer("test-module")
        assert tracer is not None
        assert hasattr(tracer, "start_span")


class TestSQLAlchemyTracing:
    def test_skipped_when_disabled(self):
        """SQLAlchemy instrumentation should be skipped when OTel is off."""
        engine = MagicMock()
        with (
            patch("app.core.tracing.get_settings") as mock_settings,
            patch(
                "opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor.instrument"
            ) as mock_instrument,
        ):
            mock_settings.return_value.otel_enabled = False
            setup_sqlalchemy_tracing(engine)
        mock_instrument.assert_not_called()
