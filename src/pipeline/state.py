"""Conversation state and debug mode management.

Provides per-user state tracking for multi-stage pipeline conversations
and debug mode toggle for verbose output.
"""

from telegram.ext import ContextTypes

from src.utils.conversation_state import ConversationState
from src.utils.logger import logger

# Per-user debug mode storage (module-level state)
_user_debug_mode: dict[int, bool] = {}


def is_debug_enabled(user_id: int) -> bool:
    """Check if debug mode is enabled for user.

    Args:
        user_id: Telegram user ID

    Returns:
        True if debug mode is enabled for this user
    """
    return _user_debug_mode.get(user_id, False)


def toggle_debug_mode(user_id: int) -> bool:
    """Toggle debug mode for user.

    Args:
        user_id: Telegram user ID

    Returns:
        New debug mode state (True = enabled, False = disabled)
    """
    current_state = _user_debug_mode.get(user_id, False)
    new_state = not current_state
    _user_debug_mode[user_id] = new_state
    return new_state


def set_debug_mode(user_id: int, enabled: bool) -> None:
    """Set debug mode for user.

    Args:
        user_id: Telegram user ID
        enabled: Debug mode state
    """
    _user_debug_mode[user_id] = enabled


def get_conversation_state(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> ConversationState:
    """Get or create conversation state for user.

    Stores state in context.user_data["conv_state"] for per-user isolation.

    Args:
        context: Telegram context with user_data
        user_id: Telegram user ID

    Returns:
        ConversationState for this user
    """
    if "conv_state" not in context.user_data:
        context.user_data["conv_state"] = ConversationState()
        logger.debug(f"Created new conversation state for user {user_id}")
    return context.user_data["conv_state"]
