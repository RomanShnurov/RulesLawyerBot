"""Telegram callback query handlers for inline keyboards.

Handles inline button callbacks for game selection and other UI interactions.
"""

from telegram import Update
from telegram.ext import ContextTypes

from src.pipeline.state import get_conversation_state
from src.utils.logger import logger


async def handle_game_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle inline button callback for game selection.

    Callback data format: "game_select:<index>" where index is:
    - A number (0-3) for game candidates
    - "other" for manual game name input

    Args:
        update: Telegram update with callback query
        context: Telegram context
    """
    query = update.callback_query
    await query.answer()  # Acknowledge callback to remove loading state

    user_id = query.from_user.id
    conv_state = get_conversation_state(context, user_id)

    # Parse callback data: "game_select:0"
    try:
        _, index_str = query.data.split(":")
        if index_str == "other":
            # User wants to enter game name manually
            conv_state.reset_pending()
            await query.edit_message_text(
                "🔤 Пожалуйста, напишите название игры на английском языке."
            )
            logger.info(f"[Pipeline] User {user_id} chose to enter game name manually")
            return

        index = int(index_str)
    except (ValueError, AttributeError):
        logger.error(f"Invalid callback data: {query.data}")
        await query.edit_message_text("❌ Invalid selection. Please try again.")
        conv_state.reset_pending()
        return

    # Validate index
    if index >= len(conv_state.game_candidates):
        logger.warning(
            f"User {user_id} selected expired game index {index}, "
            f"candidates: {len(conv_state.game_candidates)}"
        )
        await query.edit_message_text(
            "⏰ Selection expired. Please ask your question again."
        )
        conv_state.reset_pending()
        return

    # Get selected game
    selected = conv_state.game_candidates[index]
    conv_state.set_game(selected["english_name"], selected["pdf_filename"])
    conv_state.reset_pending()

    logger.info(
        f"[Pipeline] User {user_id} selected game: {selected['english_name']}"
    )

    # Update message to show selection
    await query.edit_message_text(
        f"✅ Выбрана игра: *{selected['english_name']}*\n\n"
        "Теперь задайте ваш вопрос об этой игре.",
        parse_mode="Markdown",
    )
