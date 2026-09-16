from src.logging_config import setup_logging

logger = setup_logging(__name__)


def configure_telemetry(service_name: str = "agentic-rag-platform") -> None:
    """Configure Azure Monitor OpenTelemetry if connection string is configured.
    
    No-op if APPLICATIONINSIGHTS_CONNECTION_STRING is missing/empty,
    or if azure-monitor-opentelemetry is not installed.
    """
    from src.config import APPLICATIONINSIGHTS_CONNECTION_STRING

    if not APPLICATIONINSIGHTS_CONNECTION_STRING:
        logger.info("[Telemetry]: No Application Insights connection string configured. Skipping.")
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(
            connection_string=APPLICATIONINSIGHTS_CONNECTION_STRING,
            service_name=service_name,
        )
        logger.info(f"[Telemetry]: Azure Monitor configured for service '{service_name}'.")
    except ImportError:
        logger.warning(
            "[Telemetry]: azure-monitor-opentelemetry package not installed. "
            "Telemetry initialization skipped."
        )
    except Exception as e:
        logger.error(f"[Telemetry]: Failed to configure Azure Monitor: {e}")
