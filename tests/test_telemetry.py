import pytest
from unittest.mock import patch, MagicMock

from src.monitoring.telemetry import configure_telemetry


def test_telemetry_skipped_when_no_connection_string():
    with patch("src.config.APPLICATIONINSIGHTS_CONNECTION_STRING", ""):
        # Should execute cleanly without raising an error
        configure_telemetry()


def test_telemetry_handles_missing_import():
    with patch("src.config.APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=dummy"):
        with patch.dict("sys.modules", {"azure.monitor.opentelemetry": None}):
            # Should handle ImportError gracefully
            configure_telemetry()


def test_telemetry_invokes_azure_monitor_when_configured():
    mock_azure = MagicMock()
    with patch("src.config.APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=dummy_key"):
        with patch.dict("sys.modules", {"azure.monitor.opentelemetry": mock_azure}):
            configure_telemetry()
            mock_azure.configure_azure_monitor.assert_called_once_with(
                connection_string="InstrumentationKey=dummy_key",
                service_name="agentic-rag-platform"
            )
