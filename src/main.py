"""Telegram bot entry point with async handlers.

Implements Schema-Guided Reasoning (SGR) output handling for transparent,
auditable agent responses.
"""

import asyncio
import platform
import signal

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.config import settings
from src.handlers import callbacks, commands, messages
from src.utils.logger import logger


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

    # Initialize Langfuse observability (must be done BEFORE agent creation)
    from src.utils.observability import setup_langfuse_instrumentation

    tracing_enabled = setup_langfuse_instrumentation()
    if tracing_enabled:
        logger.info("🔍 Langfuse observability enabled")
    else:
        logger.info("🔍 Langfuse observability disabled")

    # Build application
    application = ApplicationBuilder().token(settings.telegram_token).build()

    # Register post-shutdown callback to flush Langfuse traces
    async def on_shutdown(app: Application) -> None:
        """Flush Langfuse traces on application shutdown."""
        from src.utils.observability import shutdown_langfuse

        shutdown_langfuse()

    application.post_shutdown = on_shutdown

    # Register command handlers
    application.add_handler(CommandHandler("start", commands.start_command))
    application.add_handler(CommandHandler("games", commands.games_command))

    # Callback query handler for inline buttons (game selection)
    application.add_handler(
        CallbackQueryHandler(callbacks.handle_game_selection, pattern="^game_select:")
    )

    # Message handler for all text messages
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, messages.handle_message)
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
