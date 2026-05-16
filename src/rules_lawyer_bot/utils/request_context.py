"""Per-request correlation context.

Stores Telegram user/chat identifiers in contextvars so logger filters can
attach them to every log record without explicit parameter passing. The
same values are mirrored to the active Sentry scope.

ContextVars are isolated per asyncio task — concurrent handlers do not
leak context across requests.
"""

from contextvars import ContextVar
from typing import Optional

user_id_var: ContextVar[Optional[int]] = ContextVar("user_id", default=None)
username_var: ContextVar[Optional[str]] = ContextVar("username", default=None)
chat_id_var: ContextVar[Optional[int]] = ContextVar("chat_id", default=None)


def bind_request_context(
    user_id: int,
    username: Optional[str],
    chat_id: Optional[int],
) -> None:
    """Bind Telegram identifiers to the current task's logging and Sentry scope.

    Should be called at the entry point of every Telegram handler before any
    logger.info call that should carry user context.
    """
    user_id_var.set(user_id)
    username_var.set(username)
    chat_id_var.set(chat_id)

    # Mirror to Sentry scope. Imported lazily to avoid a circular dependency:
    # sentry_setup imports `logger`, which depends on this module.
    from src.rules_lawyer_bot.utils.sentry_setup import bind_user_context

    bind_user_context(user_id, username, chat_id)
