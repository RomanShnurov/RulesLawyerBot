"""Telegram bot entry point with async handlers.

Implements Schema-Guided Reasoning (SGR) output handling for transparent,
auditable agent responses.
"""

import asyncio
import json
import platform
import signal
from datetime import datetime

from agents import Runner
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.agent.definition import get_user_session, rules_agent
from src.agent.schemas import ReasonedAnswer
from src.config import settings
from src.utils.logger import logger
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

    # Main answer (always shown)
    parts.append(answer.answer)

    # Sources (if available)
    if answer.sources:
        sources_text = ", ".join(f"{s.file} ({s.location})" for s in answer.sources)
        parts.append(f"\n📖 *Источники:* {sources_text}")

    # Confidence indicator
    if answer.confidence >= 0.8:
        conf_emoji = "✅"
    elif answer.confidence >= 0.5:
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
        suggestions_text = ", ".join(answer.suggestions[:3])  # Max 3
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


# ============================================
# Message Handler
# ============================================


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all text messages using OpenAI Agent.

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

    # Send typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    try:
        # Get user-specific session
        session = get_user_session(user.id)

        # Run agent with semaphore to limit concurrent searches
        async with ugrep_semaphore:
            result = await Runner.run(
                starting_agent=rules_agent, input=message_text, session=session
            )

        # Log execution details
        logger.debug(f"Agent steps: {len(result.new_items)}")
        for i, step in enumerate(result.new_items, 1):
            # Pretty-print structured outputs, show summary for others
            if hasattr(step, 'raw_item') and hasattr(step.raw_item, 'content'):
                # Extract just the text content from message outputs
                content = step.raw_item.content
                if isinstance(content, list) and len(content) > 0:
                    text_content = content[0].text if hasattr(content[0], 'text') else str(content[0])
                    # Pretty-print JSON if it's parseable
                    try:
                        parsed = json.loads(text_content)
                        logger.debug(f"  Step {i}: {step.type}: {step.raw_item.model_dump_json(indent=2, ensure_ascii=False)}")
                        logger.debug(f"    Output (formatted):\n{json.dumps(parsed, indent=2, ensure_ascii=False)}")
                    except (json.JSONDecodeError, AttributeError):
                        # Not JSON, log first 200 chars
                        preview = text_content[:200] + "..." if len(text_content) > 200 else text_content
                        logger.debug(f"  Step {i}: {step.type} - {preview}")
                else:
                    logger.debug(f"  Step {i}: {step.type}")
            else:
                # For other step types, show summary
                logger.debug(f"  Step {i}: {type(step).__name__}")

        # Handle structured SGR output
        if isinstance(result.final_output, ReasonedAnswer):
            # Log full reasoning chain for analysis
            log_reasoning_chain(user.id, result.final_output)

            # Check if verbose mode enabled (debug mode or admin)
            is_admin = settings.admin_ids and user.id in settings.admin_ids
            debug_enabled = user_debug_mode.get(user.id, False)
            show_verbose = is_admin or debug_enabled

            # Format for Telegram display
            response_text = format_reasoned_answer(
                result.final_output,
                verbose=show_verbose,  # Show reasoning chain if debug mode
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

        await send_long_message(
            bot=context.bot, chat_id=update.effective_chat.id, text=response_text
        )

    except Exception:
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
    application.add_handler(CommandHandler("id", get_my_id))
    application.add_handler(CommandHandler("health", health_check))
    application.add_handler(CommandHandler("debug", toggle_debug))
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
