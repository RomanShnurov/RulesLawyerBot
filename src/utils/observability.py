"""Langfuse observability setup using OpenTelemetry instrumentation."""

import base64
import os
from typing import Optional

from src.config import settings
from src.utils.logger import logger


def setup_langfuse_instrumentation() -> bool:
    """Initialize Langfuse observability via OpenTelemetry instrumentation.

    Returns:
        True if instrumentation was successfully enabled, False otherwise
    """
    if not settings.tracing_enabled:
        logger.info("Langfuse tracing is disabled")
        return False

    try:
        # Configure OpenTelemetry environment variables
        auth_string = base64.b64encode(
            f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
        ).decode()

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
            f"{settings.langfuse_base_url}/api/public/otel"
        )
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {auth_string}"

        # Set resource attributes
        resource_attrs = [
            "service.name=RulesLawyerBot",
            f"deployment.environment.name={settings.langfuse_environment}",
            f"langfuse.environment={settings.langfuse_environment}",
        ]
        os.environ["OTEL_RESOURCE_ATTRIBUTES"] = ",".join(resource_attrs)

        # Import and initialize instrumentation
        from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

        # Single line of instrumentation - captures everything!
        OpenAIAgentsInstrumentor().instrument()

        logger.info(
            f"✅ Langfuse instrumentation enabled "
            f"(environment: {settings.langfuse_environment})"
        )
        return True

    except ImportError as e:
        logger.warning(f"Failed to import Langfuse instrumentation: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to setup Langfuse instrumentation: {e}", exc_info=True)
        return False


def get_trace_context_for_user(user_id: int, username: Optional[str] = None) -> dict:
    """Get OpenTelemetry span attributes for user context."""
    attrs = {
        "user.id": str(user_id),
        "user.telegram_id": user_id,
    }
    if username:
        attrs["user.username"] = username
    return attrs


def create_trace_url(trace_id: Optional[str] = None) -> Optional[str]:
    """Generate Langfuse UI URL for a specific trace."""
    if not settings.tracing_enabled or not trace_id:
        return None
    return f"{settings.langfuse_base_url}/traces/{trace_id}"
