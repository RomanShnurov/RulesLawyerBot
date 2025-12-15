"""Multi-stage pipeline output handler.

Routes pipeline outputs to appropriate Telegram UI actions based on action_type.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.agent.schemas import ActionType, PipelineOutput
from src.config import settings
from src.formatters.sgr import format_reasoned_answer, log_reasoning_chain
from src.pipeline.state import get_conversation_state, is_debug_enabled
from src.utils.conversation_state import ConversationStage
from src.utils.logger import logger
from src.utils.telegram_helpers import send_long_message


def build_game_selection_keyboard(
    candidates: list[dict], add_other_option: bool = True
) -> InlineKeyboardMarkup:
    """Build inline keyboard for game selection.

    Args:
        candidates: List of game candidates with 'english_name' and 'pdf_filename'
        add_other_option: If True, adds "Other game" button at the bottom

    Returns:
        InlineKeyboardMarkup with game selection buttons
    """
    keyboard = []
    for i, candidate in enumerate(candidates[:4]):  # Max 4 options to leave room for "Other"
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=candidate["english_name"],
                    callback_data=f"game_select:{i}",
                )
            ]
        )

    # Add "Other game" option
    if add_other_option:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="🔤 Другая игра (введу название)",
                    callback_data="game_select:other",
                )
            ]
        )

    return InlineKeyboardMarkup(keyboard)


async def handle_pipeline_output(
    output: PipelineOutput,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> None:
    """Route pipeline output based on action_type.

    Routes to:
    - CLARIFICATION_NEEDED: Ask question as text
    - GAME_SELECTION: Show inline keyboard
    - SEARCH_IN_PROGRESS: Show progress + ask question
    - FINAL_ANSWER: Format and send answer

    Args:
        output: PipelineOutput from agent
        update: Telegram update
        context: Telegram context
        user_id: Telegram user ID
    """
    conv_state = get_conversation_state(context, user_id)

    logger.info(
        f"[Pipeline] User {user_id} - action_type: {output.action_type.value}"
    )
    logger.debug(f"[Pipeline] stage_reasoning: {output.stage_reasoning}")

    if output.action_type == ActionType.CLARIFICATION_NEEDED:
        # Ask clarification question as text
        conv_state.stage = ConversationStage.AWAITING_CLARIFICATION
        conv_state.pending_question = output.clarification.question

        logger.info(f"[Pipeline] Asking clarification: {output.clarification.question}")

        await update.message.reply_text(
            f"❓ {output.clarification.question}"
        )

    elif output.action_type == ActionType.GAME_SELECTION:
        # Show inline keyboard for game selection
        conv_state.stage = ConversationStage.AWAITING_GAME_SELECTION
        conv_state.game_candidates = [
            {"english_name": c.english_name, "pdf_filename": c.pdf_filename}
            for c in output.game_identification.candidates
        ]

        keyboard = build_game_selection_keyboard(conv_state.game_candidates)

        logger.info(
            f"[Pipeline] Showing game selection: {len(conv_state.game_candidates)} options"
        )

        await update.message.reply_text(
            f"🎮 {output.clarification.question}",
            reply_markup=keyboard,
        )

    elif output.action_type == ActionType.SEARCH_IN_PROGRESS:
        # Need more info during search
        conv_state.stage = ConversationStage.AWAITING_CLARIFICATION
        conv_state.pending_question = output.search_progress.additional_question

        # Update game context
        conv_state.set_game(
            output.search_progress.game_name,
            output.search_progress.pdf_file,
        )

        logger.info(
            f"[Pipeline] Search in progress, asking: {output.search_progress.additional_question}"
        )

        await update.message.reply_text(
            f"🔍 Ищу в правилах {output.search_progress.game_name}...\n\n"
            f"❓ {output.search_progress.additional_question}"
        )

    elif output.action_type == ActionType.FINAL_ANSWER:
        # Complete answer - update game context and send response
        conv_state.reset_pending()

        if output.game_identification:
            conv_state.set_game(
                output.game_identification.identified_game,
                output.game_identification.pdf_file,
            )
            logger.debug(
                f"[Pipeline] Set game context: {output.game_identification.identified_game}"
            )

        # Use existing format_reasoned_answer function
        debug_enabled = is_debug_enabled(user_id)
        is_admin = settings.admin_ids and user_id in settings.admin_ids
        response_text = format_reasoned_answer(
            output.final_answer,
            verbose=debug_enabled or is_admin,
        )

        log_reasoning_chain(user_id, output.final_answer)

        await send_long_message(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            text=response_text,
        )
