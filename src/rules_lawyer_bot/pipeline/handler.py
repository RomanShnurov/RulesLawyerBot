"""Multi-stage pipeline output handler.

Routes pipeline outputs to appropriate Telegram UI actions based on action_type.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.rules_lawyer_bot.agent.schemas import ActionType, PipelineOutput
from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.pipeline.state import get_conversation_state
from src.rules_lawyer_bot.utils.conversation_state import ConversationStage
from src.rules_lawyer_bot.utils.logger import logger
from src.rules_lawyer_bot.utils.telegram_helpers import send_long_message


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
    if update.message is None or update.effective_chat is None:
        logger.warning("[Pipeline] update has no message/chat, dropping output")
        return
    message = update.message
    chat = update.effective_chat

    conv_state = get_conversation_state(context, user_id)

    logger.info(
        f"[Pipeline] User {user_id} - action_type: {output.action_type.value}"
    )
    logger.debug(f"[Pipeline] stage_reasoning: {output.stage_reasoning}")

    if output.action_type == ActionType.CLARIFICATION_NEEDED:
        # Ask clarification question as text. The model_validator guarantees
        # `clarification` is populated for this action_type.
        assert output.clarification is not None
        conv_state.stage = ConversationStage.AWAITING_CLARIFICATION
        conv_state.pending_question = output.clarification.question

        logger.info(f"[Pipeline] Asking clarification: {output.clarification.question}")

        await message.reply_text(
            f"❓ {output.clarification.question}"
        )

    elif output.action_type == ActionType.GAME_SELECTION:
        # Show inline keyboard for game selection. The model_validator
        # guarantees both fields are populated for this action_type.
        assert output.game_identification is not None
        assert output.clarification is not None
        conv_state.stage = ConversationStage.AWAITING_GAME_SELECTION
        conv_state.game_candidates = [
            {"english_name": c.english_name, "pdf_filename": c.pdf_filename}
            for c in output.game_identification.candidates
        ]

        keyboard = build_game_selection_keyboard(conv_state.game_candidates)

        logger.info(
            f"[Pipeline] Showing game selection: {len(conv_state.game_candidates)} options"
        )

        await message.reply_text(
            f"🎮 {output.clarification.question}",
            reply_markup=keyboard,
        )

    elif output.action_type == ActionType.SEARCH_IN_PROGRESS:
        # Need more info during search. The model_validator guarantees
        # `search_progress` is populated for this action_type.
        assert output.search_progress is not None
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

        await message.reply_text(
            f"🔍 Ищу в правилах {output.search_progress.game_name}...\n\n"
            f"❓ {output.search_progress.additional_question}"
        )

    elif output.action_type == ActionType.FINAL_ANSWER:
        # Complete answer - update game context and send response
        conv_state.reset_pending()

        gi = output.game_identification
        if gi and gi.identified_game and gi.pdf_file:
            conv_state.set_game(gi.identified_game, gi.pdf_file)
            logger.debug(
                f"[Pipeline] Set game context: {gi.identified_game}"
            )

        # Format final answer for display. The model_validator guarantees
        # `final_answer` is populated for this action_type.
        assert output.final_answer is not None
        parts = [output.final_answer.answer]

        # Add confidence indicator if low confidence
        if output.final_answer.confidence < 0.8:
            conf_emoji = "⚠️" if output.final_answer.confidence >= 0.5 else "❓"
            parts.append(
                f"\n{conf_emoji} Уверенность: {output.final_answer.confidence:.0%}"
            )

        # Add limitations if any
        if output.final_answer.limitations:
            limitations_text = "; ".join(output.final_answer.limitations)
            parts.append(f"\n⚠️ *Ограничения:* {limitations_text}")

        # Add suggestions for follow-up questions
        if output.final_answer.suggestions:
            suggestions_text = " • ".join(output.final_answer.suggestions[:3])
            parts.append(f"\n💡 *См. также:* {suggestions_text}")

        # Add reasoning trace for admin users (ReAct-inspired transparency)
        if user_id in settings.admin_ids and output.stage_reasoning:
            parts.append("\n" + "─" * 40)
            parts.append("🔬 *Reasoning Trace (Admin Only):*")
            parts.append(f"```\n{output.stage_reasoning}\n```")

        response_text = "\n".join(parts)

        logger.info(
            f"[Pipeline] Final answer sent (confidence: {output.final_answer.confidence:.0%})"
        )

        await send_long_message(
            bot=context.bot,
            chat_id=chat.id,
            text=response_text,
        )
