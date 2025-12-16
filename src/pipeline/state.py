"""Conversation state management.

Provides per-user state tracking for multi-stage pipeline conversations.
"""

from telegram.ext import ContextTypes

from src.utils.conversation_state import ConversationState
from src.utils.logger import logger


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
