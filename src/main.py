"""Telegram bot entry point with async handlers."""
import asyncio
import platform
import signal
from datetime import datetime

from agents import Runner
from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

from src.agent.definition import get_user_session, rules_agent
from src.config import settings
from src.utils.logger import logger
from src.utils.safety import rate_limiter, ugrep_semaphore
from src.utils.telegram_helpers import send_long_message

# Track bot uptime
bot_start_time = datetime.now()


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
👋 Welcome, {user.first_name}!

I'm your Board Game Rules Referee. Ask me anything about your board game rules!

**How to use:**
1. Ask a question about game rules (e.g., "How does movement work in Gloomhaven?")
2. I'll search through PDF rulebooks and provide answers
3. You can ask follow-up questions - I remember our conversation!

**Commands:**
- /start - Show this welcome message
- /id - Get your Telegram user ID

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
        parse_mode="Markdown"
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
        logger.warning(f"Unauthorized /health attempt by user {user.id} ({user.username})")
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
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        # Get user-specific session
        session = get_user_session(user.id)

        # Run agent with semaphore to limit concurrent searches
        async with ugrep_semaphore:
            result = await Runner.run(
                agent=rules_agent,
                input=message_text,
                session=session
            )

        # Log execution details
        logger.debug(f"Agent steps: {len(result.steps)}")
        for step in result.steps:
            logger.debug(f"  Step: {step}")

        # Send response (with message splitting)
        response_text = result.final_output or "No response generated"
        await send_long_message(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            text=response_text
        )

    except Exception as e:
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
    application = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .build()
    )

    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("id", get_my_id))
    application.add_handler(CommandHandler("health", health_check))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Register graceful shutdown handlers (platform-specific)
    # Note: loop.add_signal_handler() is not supported on Windows
    # In production (Docker/Linux), signal handlers work properly
    # On Windows, python-telegram-bot handles shutdown automatically
    if platform.system() != "Windows":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(shutdown(application))
            )
        logger.info("Registered signal handlers for graceful shutdown")
    else:
        logger.info("Running on Windows - using default shutdown handling")

    # Run bot in polling mode
    logger.info("Bot started. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
