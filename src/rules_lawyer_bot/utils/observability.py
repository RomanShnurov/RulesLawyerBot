"""Langfuse observability setup using Pydantic Logfire instrumentation.

Uses the OpenAI-recommended Logfire approach for agent tracing.
See: https://cookbook.openai.com/examples/agents_sdk/evaluate_agents
"""

import base64
from typing import TYPE_CHECKING, Optional

from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.utils.logger import logger

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

# Global reference to span processor for manual flushing
_span_processor: Optional["SimpleSpanProcessor"] = None


def setup_langfuse_instrumentation() -> bool:
    """Initialize Langfuse observability via Pydantic Logfire instrumentation.

    Uses the OpenAI-recommended pattern with Logfire for automatic
    instrumentation of OpenAI Agents SDK.

    Returns:
        True if instrumentation was successfully enabled, False otherwise
    """
    if not settings.tracing_enabled:
        logger.info("Langfuse tracing is disabled")
        return False

    try:
        # Build Langfuse OTLP endpoint and auth header
        auth_string = base64.b64encode(
            f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
        ).decode()

        otlp_endpoint = f"{settings.langfuse_base_url}/api/public/otel"
        otlp_headers = {"Authorization": f"Basic {auth_string}"}

        global _span_processor

        # Configure OpenTelemetry OTLP exporter for Langfuse
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        langfuse_exporter = OTLPSpanExporter(
            endpoint=f"{otlp_endpoint}/v1/traces",
            headers=otlp_headers,
            timeout=30,  # 30 second timeout
        )

        # Store processor reference for manual flushing
        _span_processor = SimpleSpanProcessor(langfuse_exporter)

        # Import and configure Logfire (OpenAI-recommended approach)
        import logfire

        # Configure Logfire with custom processor for Langfuse export
        logfire.configure(
            service_name="RulesLawyerBot",
            send_to_logfire=False,  # Don't send to Logfire cloud
            console=False,  # Disable console output for traces
            additional_span_processors=[_span_processor],
        )

        # Instrument OpenAI Agents SDK
        logfire.instrument_openai_agents()

        logger.info(
            f"✅ Langfuse instrumentation enabled via Logfire "
            f"(environment: {settings.langfuse_environment}, endpoint: {otlp_endpoint})"
        )
        return True

    except ImportError as e:
        logger.warning(f"Failed to import Logfire instrumentation: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to setup Langfuse instrumentation: {e}", exc_info=True)
        return False


def get_trace_context_for_user(user_id: int, username: Optional[str] = None) -> dict:
    """Get OpenTelemetry span attributes for user context.

    Sets both OpenTelemetry standard attributes and Langfuse-specific attributes
    for better user tracking and filtering in Langfuse UI.

    Args:
        user_id: Telegram user ID
        username: Optional Telegram username

    Returns:
        Dictionary of OpenTelemetry span attributes
    """
    attrs = {
        # OpenTelemetry standard attributes
        "user.id": str(user_id),
        "user.telegram_id": user_id,
        # Langfuse-specific user attributes (for Langfuse UI filtering)
        "langfuse.user.id": str(user_id),
    }
    if username:
        attrs["user.username"] = username
        # Langfuse-specific user name
        attrs["langfuse.user.name"] = username
    return attrs


def create_trace_url(trace_id: Optional[str] = None) -> Optional[str]:
    """Generate Langfuse UI URL for a specific trace.

    Args:
        trace_id: OpenTelemetry trace ID (32-character hex string)

    Returns:
        Langfuse trace URL or None if tracing is disabled
    """
    if not settings.tracing_enabled or not trace_id:
        return None
    return f"{settings.langfuse_base_url}/traces/{trace_id}"


def flush_langfuse(timeout_millis: int = 30000) -> bool:
    """Manually flush all pending traces to Langfuse.

    Important for short-lived applications (serverless, scripts, notebooks)
    to ensure all events are exported before the application exits.

    Args:
        timeout_millis: Maximum time to wait for flush in milliseconds

    Returns:
        True if flush was successful, False otherwise
    """
    if _span_processor is None:
        logger.debug("No span processor to flush (tracing not enabled)")
        return False

    try:
        result = _span_processor.force_flush(timeout_millis)
        if result:
            logger.info("✅ Langfuse traces flushed successfully")
        else:
            logger.warning("⚠️ Langfuse flush timed out or failed")
        return result
    except Exception as e:
        logger.error(f"Failed to flush Langfuse traces: {e}")
        return False


def shutdown_langfuse(timeout_millis: int = 30000) -> None:
    """Shutdown Langfuse instrumentation and flush remaining traces.

    Should be called during application shutdown to ensure all traces
    are exported and resources are released.

    Args:
        timeout_millis: Maximum time to wait for shutdown in milliseconds
    """
    if _span_processor is None:
        return

    try:
        # Shutdown will automatically flush pending spans
        _span_processor.shutdown()
        logger.info("✅ Langfuse instrumentation shutdown complete")
    except Exception as e:
        logger.error(f"Error during Langfuse shutdown: {e}")
