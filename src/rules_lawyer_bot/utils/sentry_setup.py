"""Sentry error tracking setup.

Initializes the Sentry SDK with logging + asyncio integrations. APM tracing
is disabled by default because the project uses OpenTelemetry → Langfuse for
distributed tracing — enabling Sentry traces would produce duplicate spans.
"""

import logging
from typing import Optional

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.types import Event, Hint

from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.utils.logger import logger


def setup_sentry() -> bool:
    """Initialize the Sentry SDK if a DSN is configured.

    Returns:
        True if Sentry was initialized, False otherwise.
    """
    if not settings.sentry_enabled:
        logger.info("Sentry disabled (SENTRY_DSN not set)")
        return False

    try:
        logging_integration = LoggingIntegration(
            level=None,         # disable breadcrumb capture (Logfire/OTel covers this)
            event_level=logging.ERROR,  # send ERROR+ logs as Sentry events
        )

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            release=settings.sentry_release or None,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            send_default_pii=False,
            integrations=[
                logging_integration,
                AsyncioIntegration(),
            ],
            # Project-level tags so all events are filterable in Sentry UI
            before_send=_add_default_tags,
        )

        logger.info(
            f"✅ Sentry initialized (environment={settings.sentry_environment}, "
            f"traces_sample_rate={settings.sentry_traces_sample_rate})"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to initialize Sentry: {e}", exc_info=True)
        return False


def _add_default_tags(event: Event, hint: Hint) -> Optional[Event]:
    """Attach project-wide tags to every Sentry event."""
    event.setdefault("tags", {})
    event["tags"].setdefault("service", "RulesLawyerBot")
    event["tags"].setdefault("openai_model", settings.openai_model)
    return event


def bind_user_context(user_id: int, username: Optional[str], chat_id: Optional[int]) -> None:
    """Attach Telegram user context to the current Sentry scope.

    Call this inside an isolation_scope so the binding does not leak between
    concurrent message handlers.
    """
    if not settings.sentry_enabled:
        return

    scope = sentry_sdk.get_current_scope()
    scope.set_user({"id": user_id, "username": username})
    if chat_id is not None:
        scope.set_tag("telegram.chat_id", chat_id)
