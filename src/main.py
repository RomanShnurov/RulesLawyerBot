"""Telegram bot entry point with async handlers.

Implements Schema-Guided Reasoning (SGR) output handling for transparent,
auditable agent responses.
"""

import asyncio
import json
import platform
import signal
from datetime import datetime
from pathlib import Path

from agents import Runner
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.agent.definition import get_user_session, rules_agent
from src.agent.schemas import ActionType, PipelineOutput, ReasonedAnswer
from src.utils.conversation_state import ConversationStage, ConversationState
from src.config import settings
from src.utils.logger import logger
from src.utils.progress_reporter import ProgressReporter
from src.utils.safety import rate_limiter, ugrep_semaphore
from src.utils.telegram_helpers import send_long_message

# Track bot uptime
bot_start_time = datetime.now()

# Per-user debug mode storage
user_debug_mode: dict[int, bool] = {}


# ============================================
# SGR Output Formatting
# ============================================


def format_reasoned_answer(answer: ReasonedAnswer, verbose: bool = False) -> str:
    """Format structured SGR answer for Telegram display.

    Args:
        answer: The structured answer from the agent
        verbose: If True, include full reasoning chain (for debugging)

    Returns:
        Formatted markdown string for Telegram
    """
    parts = []

    # Main answer (always shown) - now includes direct quotes and sources
    parts.append(answer.answer)

    # Confidence indicator (only if not high confidence)
    if answer.confidence < 0.8:
        if answer.confidence >= 0.5:
            conf_emoji = "⚠️"
        else:
            conf_emoji = "❓"
        parts.append(f"\n{conf_emoji} Уверенность: {answer.confidence:.0%}")

    # Limitations (if any)
    if answer.limitations:
        limitations_text = "; ".join(answer.limitations)
        parts.append(f"\n⚠️ *Ограничения:* {limitations_text}")

    # Suggestions for follow-up questions
    if answer.suggestions:
        suggestions_text = " • ".join(answer.suggestions[:3])  # Max 3
        parts.append(f"\n💡 *См. также:* {suggestions_text}")

    # Verbose mode: show full reasoning chain
    if verbose:
        parts.append("\n\n" + "═" * 30)
        parts.append("*REASONING CHAIN*")
        parts.append("═" * 30)

        # Query Analysis
        qa = answer.query_analysis
        parts.append("\n*1. Query Analysis*")
        parts.append(f"  Type: {qa.query_type.value}")
        parts.append(f"  Game: {qa.game_name or 'Not specified'}")
        parts.append(f"  Interpreted: {qa.interpreted_question}")
        parts.append(f"  Concepts: {', '.join(qa.primary_concepts)}")
        if qa.potential_dependencies:
            parts.append(f"  Dependencies: {', '.join(qa.potential_dependencies)}")
        parts.append(f"  Reasoning: {qa.reasoning}")

        # Search Plan
        sp = answer.search_plan
        parts.append("\n*2. Search Plan*")
        parts.append(f"  File: {sp.target_file or 'To be determined'}")
        parts.append(f"  Terms: {', '.join(sp.search_terms)}")
        parts.append(f"  Strategy: {sp.search_strategy}")
        parts.append(f"  Reasoning: {sp.reasoning}")

        # Primary Search Result
        psr = answer.primary_search_result
        parts.append("\n*3. Primary Search*")
        parts.append(f"  Term: {psr.search_term}")
        parts.append(f"  Found: {'Yes' if psr.found else 'No'}")
        parts.append(f"  Completeness: {psr.completeness_score:.0%}")
        if psr.relevant_excerpts:
            excerpts = psr.relevant_excerpts[:2]  # Max 2 excerpts
            for i, excerpt in enumerate(excerpts, 1):
                truncated = excerpt[:100] + "..." if len(excerpt) > 100 else excerpt
                parts.append(f"  Excerpt {i}: {truncated}")
        if psr.referenced_concepts:
            parts.append(f"  References: {', '.join(psr.referenced_concepts)}")
        parts.append(f"  Analysis: {psr.reasoning}")

        # Follow-up Searches
        if answer.follow_up_searches:
            parts.append(
                f"\n*4. Follow-up Searches ({len(answer.follow_up_searches)})*"
            )
            for i, fs in enumerate(answer.follow_up_searches, 1):
                parts.append(f"  [{i}] {fs.concept}")
                parts.append(f"      Why: {fs.why_needed}")
                parts.append(f"      Found: {fs.found_info[:80]}...")
                parts.append(
                    f"      Useful: {'Yes' if fs.contributed_to_answer else 'No'}"
                )

    return "\n".join(parts)


# ============================================
# Multi-Stage Pipeline Helpers
# ============================================


def get_conversation_state(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> ConversationState:
    """Get or create conversation state for user.

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
        debug_enabled = user_debug_mode.get(user_id, False)
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


def log_reasoning_chain(user_id: int, answer: ReasonedAnswer) -> None:
    """Log the full reasoning chain for debugging and analysis.

    Args:
        user_id: Telegram user ID
        answer: The structured answer from the agent
    """
    logger.info(f"[SGR] User {user_id} - Reasoning Chain:")

    # Query Analysis
    qa = answer.query_analysis
    logger.info(f"  [Query] Type: {qa.query_type.value}, Game: {qa.game_name}")
    logger.info(f"  [Query] Interpreted: {qa.interpreted_question}")
    logger.info(f"  [Query] Concepts: {qa.primary_concepts}")

    # Search Plan
    sp = answer.search_plan
    logger.info(f"  [Plan] File: {sp.target_file}, Strategy: {sp.search_strategy}")
    logger.info(f"  [Plan] Terms: {sp.search_terms}")

    # Primary Search
    psr = answer.primary_search_result
    logger.info(
        f"  [Search] Found: {psr.found}, Completeness: {psr.completeness_score:.0%}"
    )
    logger.info(f"  [Search] Referenced: {psr.referenced_concepts}")

    # Follow-ups
    if answer.follow_up_searches:
        for i, fs in enumerate(answer.follow_up_searches, 1):
            logger.info(f"  [Follow-up {i}] {fs.concept}: {fs.contributed_to_answer}")

    # Final
    logger.info(f"  [Result] Confidence: {answer.confidence:.0%}")
    logger.info(f"  [Result] Sources: {len(answer.sources)}")
    if answer.limitations:
        logger.info(f"  [Result] Limitations: {answer.limitations}")


# ============================================
# Command Handlers
# ============================================


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command.

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started bot")

    welcome_message = f"""
Welcome, {user.first_name}!

I'm your Board Game Rules Referee. Ask me anything about your board game rules!

**How to use:**
1. Ask a question about game rules (e.g., "How does movement work in Gloomhaven?")
2. I'll search through PDF rulebooks and provide answers
3. You can ask follow-up questions - I remember our conversation!

**Commands:**
- /start - Show this welcome message
- /games - List available rulebooks (or search: /games <name>)
- /id - Get your Telegram user ID
- /debug - Toggle verbose mode (see my reasoning process)

**Tips:**
- Use game names in English (e.g., "Arkham Horror" not "Ужас Аркхэма")
- For Russian text search, I'll use smart regex patterns
- Rate limit: {settings.max_requests_per_minute} requests per minute

Type your question to get started!
""".strip()

    await update.message.reply_text(welcome_message)


async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /id command - show user's Telegram ID.

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) requested their ID")

    await update.message.reply_text(
        f"👤 Your Telegram User ID: `{user.id}`\n\n"
        f"Name: {user.first_name} {user.last_name or ''}\n"
        f"Username: @{user.username or 'N/A'}",
        parse_mode="Markdown",
    )


async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /health command for monitoring (admin only).

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user

    # Check if user is admin
    if not settings.admin_ids or user.id not in settings.admin_ids:
        logger.warning(
            f"Unauthorized /health attempt by user {user.id} ({user.username})"
        )
        await update.message.reply_text(
            "🚫 Unauthorized. This command is restricted to administrators."
        )
        return

    uptime = (datetime.now() - bot_start_time).total_seconds()

    await update.message.reply_text(
        f"✅ Bot is healthy\n"
        f"⏱️ Uptime: {uptime:.0f}s\n"
        f"📊 Rate limit: {settings.max_requests_per_minute} req/min\n"
        f"👤 Your User ID: {user.id}"
    )


async def toggle_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /debug command - toggle verbose reasoning output.

    When enabled, shows the full SGR reasoning chain including:
    - How the question was understood
    - What searches were performed
    - Key findings from the rulebook
    - Additional context gathered

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user
    current_state = user_debug_mode.get(user.id, False)
    new_state = not current_state
    user_debug_mode[user.id] = new_state

    logger.info(f"User {user.id} ({user.username}) toggled debug mode: {new_state}")

    if new_state:
        await update.message.reply_text(
            "🔍 *Debug mode enabled*\n\n"
            "You will now see the full reasoning chain:\n"
            "• How I understood your question\n"
            "• What searches I performed\n"
            "• Key findings from the rulebook\n"
            "• Additional context gathered\n\n"
            "Use /debug again to disable.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🔇 *Debug mode disabled*\n\n"
            "You will now see only the answer.\n"
            "Use /debug to enable verbose output.",
            parse_mode="Markdown",
        )


async def games_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available games with optional search query.

    Usage:
        /games              → List all available games
        /games <query>      → Search for specific game (fuzzy matching)

    Examples:
        /games
        /games wingspan
        /games gloomy       → finds "Gloomhaven"

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) requested game list via /games")

    # Extract search query from command args
    query = " ".join(context.args).strip() if context.args else ""

    try:
        pdf_dir = Path(settings.pdf_storage_path)
        if not pdf_dir.exists():
            await update.message.reply_text("⚠️ PDF library not found.")
            return

        # Get all PDF filenames (without .pdf extension)
        all_games = sorted([f.stem for f in pdf_dir.glob("*.pdf")])

        if not all_games:
            await update.message.reply_text("📚 The game library is currently empty.")
            return

        # If query provided: search with fuzzy matching
        if query:
            query_lower = query.lower()

            # Exact matches first, then partial matches
            exact_matches = [g for g in all_games if query_lower == g.lower()]
            partial_matches = [
                g for g in all_games
                if query_lower in g.lower() and g not in exact_matches
            ]

            matches = exact_matches + partial_matches

            if not matches:
                # No matches found - show closest alternatives (top 3)
                # Simple heuristic: count matching characters
                def match_score(game: str) -> int:
                    game_lower = game.lower()
                    return sum(1 for c in query_lower if c in game_lower)

                suggestions = sorted(all_games, key=match_score, reverse=True)[:3]

                response = f"❌ Игра '{query}' не найдена.\n\n"
                response += "💡 Возможно, вы имели в виду:\n"
                for i, game in enumerate(suggestions, 1):
                    response += f"{i}. 📖 {game}\n"
                response += f"\n🎮 Всего игр в библиотеке: {len(all_games)}"
                response += "\n\n💬 Используйте /games для просмотра всех игр"

                await update.message.reply_text(response)
                return

            # Found matches - show them
            if len(matches) == 1:
                response = f"✅ Найдена игра: *{matches[0]}*\n\n"
                response += "💬 Можете задать любой вопрос о правилах этой игры!"
            else:
                response = f"🔍 Найдено игр: {len(matches)}\n\n"
                for i, game in enumerate(matches[:10], 1):  # Show max 10
                    response += f"{i}. 📖 {game}\n"
                if len(matches) > 10:
                    response += f"\n... и еще {len(matches) - 10} игр"

            await update.message.reply_text(response, parse_mode="Markdown")
            return

        # No query: show all games
        response = f"🎮 *Доступные игры ({len(all_games)}):*\n\n"

        for i, game in enumerate(all_games, 1):
            response += f"{i}. 📖 {game}\n"

        response += "\n💡 *Как задать вопрос:*\n"
        response += 'Просто напишите: "Как работает движение в Dead Cells?"\n\n'
        response += "🔍 *Поиск игры:*\n"
        response += "Используйте /games <название> для поиска конкретной игры"

        await send_long_message(context.bot, update.effective_chat.id, response)

    except Exception as e:
        logger.exception(f"Error in games_command: {e}")
        await update.message.reply_text("⚠️ Ошибка при получении списка игр.")


# ============================================
# Callback Query Handler (Inline Buttons)
# ============================================


async def handle_game_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle inline button callback for game selection.

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


# ============================================
# Message Handler
# ============================================


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all text messages using multi-stage pipeline.

    Args:
        update: Telegram update object
        context: Telegram context
    """
    user = update.effective_user
    message_text = update.message.text

    logger.info(f"User {user.id}: {message_text[:100]}")

    # Check rate limit
    allowed, rate_limit_msg = await rate_limiter.check_rate_limit(user.id)
    if not allowed:
        await update.message.reply_text(f"⏳ {rate_limit_msg}")
        return

    # Get conversation state
    conv_state = get_conversation_state(context, user.id)

    # Build context-aware input for agent
    agent_input = message_text

    # Inject game context if available
    if conv_state.has_game_context():
        agent_input = (
            f"[Context: Current game is '{conv_state.current_game}', "
            f"PDF: '{conv_state.current_pdf}']\n\n"
            f"User question: {message_text}"
        )
        logger.debug(
            f"[Pipeline] Injected game context: {conv_state.current_game}"
        )

    # Send typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    # Create progress reporter for streaming updates
    progress = ProgressReporter(context.bot, update.effective_chat.id)

    try:
        # Get user-specific session
        logger.debug(f"[Perf] Getting session for user {user.id}")
        session = get_user_session(user.id)
        logger.debug(f"[Perf] Session loaded, starting agent run")

        # Run agent with streaming to show progress
        async with ugrep_semaphore:
            logger.debug(f"[Perf] Acquired ugrep semaphore, calling Runner.run_streamed")
            result = Runner.run_streamed(
                starting_agent=rules_agent, input=agent_input, session=session
            )
            logger.debug(f"[Perf] Runner.run_streamed returned, waiting for first event")

            # Process streaming events
            event_count = 0
            async for event in result.stream_events():
                event_count += 1
                if event_count == 1:
                    logger.debug(f"[Perf] First event received: {event.type}")

                if event.type == "run_item_stream_event":
                    item = event.item
                    if item.type == "tool_call_item":
                        # Extract tool name and arguments
                        tool_name = getattr(item, "name", None)
                        if tool_name is None and hasattr(item, "raw_item"):
                            tool_name = getattr(item.raw_item, "name", "unknown")

                        # Extract arguments if available
                        args = None
                        if hasattr(item, "raw_item") and hasattr(item.raw_item, "arguments"):
                            try:
                                args = json.loads(item.raw_item.arguments)
                            except (json.JSONDecodeError, TypeError):
                                pass

                        logger.debug(f"[Perf] Tool call event received: {tool_name}")
                        await progress.report_tool_call(tool_name, args)
                        logger.debug(f"Tool called: {tool_name}")

        # Force final update before response
        await progress.force_update()

        # Log execution details
        logger.debug(f"Agent steps: {len(result.new_items)}")
        for i, step in enumerate(result.new_items, 1):
            # Pretty-print structured outputs, show summary for others
            if hasattr(step, "raw_item") and hasattr(step.raw_item, "content"):
                # Extract just the text content from message outputs
                content = step.raw_item.content
                if isinstance(content, list) and len(content) > 0:
                    text_content = (
                        content[0].text
                        if hasattr(content[0], "text")
                        else str(content[0])
                    )
                    # Pretty-print JSON if it's parseable
                    try:
                        parsed = json.loads(text_content)
                        logger.debug(
                            f"  Step {i}: {step.type}: "
                            f"{step.raw_item.model_dump_json(indent=2, ensure_ascii=False)}"
                        )
                        logger.debug(
                            f"    Output (formatted):\n"
                            f"{json.dumps(parsed, indent=2, ensure_ascii=False)}"
                        )
                    except (json.JSONDecodeError, AttributeError):
                        # Not JSON, log first 200 chars
                        preview = (
                            text_content[:200] + "..."
                            if len(text_content) > 200
                            else text_content
                        )
                        logger.debug(f"  Step {i}: {step.type} - {preview}")
                else:
                    logger.debug(f"  Step {i}: {step.type}")
            else:
                # For other step types, show summary
                logger.debug(f"  Step {i}: {type(step).__name__}")

        # Handle multi-stage pipeline output
        if isinstance(result.final_output, PipelineOutput):
            # Delete progress message before sending response
            await progress.finalize()
            await handle_pipeline_output(
                result.final_output, update, context, user.id
            )
        elif isinstance(result.final_output, ReasonedAnswer):
            # Backward compatibility: handle old ReasonedAnswer format
            log_reasoning_chain(user.id, result.final_output)

            is_admin = settings.admin_ids and user.id in settings.admin_ids
            debug_enabled = user_debug_mode.get(user.id, False)

            response_text = format_reasoned_answer(
                result.final_output,
                verbose=is_admin or debug_enabled,
            )

            # Delete progress message before sending response
            await progress.finalize()
            await send_long_message(
                bot=context.bot, chat_id=update.effective_chat.id, text=response_text
            )
        else:
            # Fallback for non-structured output
            response_text = (
                str(result.final_output)
                if result.final_output
                else "No response generated"
            )
            logger.warning(
                f"Non-structured output received: {type(result.final_output)}"
            )
            # Delete progress message before sending response
            await progress.finalize()
            await send_long_message(
                bot=context.bot, chat_id=update.effective_chat.id, text=response_text
            )

    except Exception:
        # Clean up progress message on error
        await progress.finalize()
        logger.exception(f"Error handling message from user {user.id}")
        await update.message.reply_text(
            "❌ An error occurred while processing your request. "
            "Please try again or contact support."
        )


# ============================================
# Application Lifecycle
# ============================================


async def shutdown(application: Application) -> None:
    """Graceful shutdown handler.

    Args:
        application: Telegram application instance
    """
    logger.info("Shutting down gracefully...")
    await application.stop()
    await application.shutdown()
    logger.info("Shutdown complete")


def main() -> None:
    """Main entry point for the bot."""
    logger.info("Starting Board Game Rules Bot")
    logger.info(f"OpenAI Model: {settings.openai_model}")
    logger.info(f"PDF Storage: {settings.pdf_storage_path}")

    # Build application
    application = ApplicationBuilder().token(settings.telegram_token).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("games", games_command))
    application.add_handler(CommandHandler("id", get_my_id))
    application.add_handler(CommandHandler("health", health_check))
    application.add_handler(CommandHandler("debug", toggle_debug))

    # Callback query handler for inline buttons (game selection)
    application.add_handler(
        CallbackQueryHandler(handle_game_selection, pattern="^game_select:")
    )

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Register graceful shutdown handlers (platform-specific)
    # Note: loop.add_signal_handler() is not supported on Windows
    # In production (Docker/Linux), signal handlers work properly
    # On Windows, python-telegram-bot handles shutdown automatically
    if platform.system() != "Windows":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(shutdown(application))
            )
        logger.info("Registered signal handlers for graceful shutdown")
    else:
        logger.info("Running on Windows - using default shutdown handling")

    # Run bot in polling mode
    logger.info("Bot started. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
