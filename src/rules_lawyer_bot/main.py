"""Telegram bot entry point with async handlers.

Implements Schema-Guided Reasoning (SGR) output handling for transparent,
auditable agent responses.
"""

import asyncio
import platform
import signal

import sentry_sdk
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from src.rules_lawyer_bot.config import settings
from src.rules_lawyer_bot.handlers import callbacks, commands, messages
from src.rules_lawyer_bot.utils import health, retention
from src.rules_lawyer_bot.utils.logger import logger


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


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch unhandled errors raised by python-telegram-bot and forward to Sentry.

    Handler-level try/except already covers most user-facing flows; this is
    the last line of defence for errors raised outside our handlers (callback
    dispatching, job queue, network layer).
    """
    logger.exception("Unhandled error in PTB dispatch", exc_info=context.error)
    if settings.sentry_enabled and context.error is not None:
        sentry_sdk.capture_exception(context.error)


async def _track_update(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """TypeHandler callback: bump the last-update-seen marker.

    Registered in group=-1 so it runs before user-facing handlers, and with
    block=False so it never delays them.
    """
    health.record_update()


def main() -> None:
    """Main entry point for the bot."""
    # Initialize Sentry FIRST so errors during the rest of startup are captured
    from src.rules_lawyer_bot.utils.sentry_setup import setup_sentry

    setup_sentry()

    logger.info("Starting Board Game Rules Bot")
    logger.info(f"OpenAI Model: {settings.openai_model}")
    logger.info(f"PDF Storage: {settings.pdf_storage_path}")

    # Initialize Langfuse observability (must be done BEFORE agent creation)
    from src.rules_lawyer_bot.utils.observability import setup_langfuse_instrumentation

    # setup_langfuse_instrumentation() also neutralises the Agents SDK's
    # built-in api.openai.com trace exporter in every branch (it 401s
    # behind a proxy key) — see observability.py.
    tracing_enabled = setup_langfuse_instrumentation()
    if tracing_enabled:
        logger.info("🔍 Langfuse observability enabled")
    else:
        logger.info("🔍 Langfuse observability disabled")

    # Initialize health state BEFORE building the application so the started_at
    # timestamp reflects "process start" rather than "first request".
    health.init_state()

    # Build application.
    # concurrent_updates=True: each update is processed in its own task, so
    # a single slow/stalled request can't block the dispatcher and freeze
    # the bot for every other user and every later message. The per-agent
    # wall-clock timeout still bounds any individual stuck request.
    application = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .concurrent_updates(True)
        .build()
    )

    # Bring up the /health endpoint + heartbeat task once the asyncio loop
    # is running. post_init fires after Application.initialize().
    async def on_startup(app: Application) -> None:
        await health.start_health_server(settings.health_host, settings.health_port)
        health.start_heartbeat(settings.heartbeat_interval_seconds)
        retention.start_cleanup(settings.retention_cleanup_interval_seconds)

    application.post_init = on_startup

    # Tear down health side-channel + flush Langfuse on shutdown.
    async def on_shutdown(app: Application) -> None:
        await retention.stop_cleanup()
        await health.stop_heartbeat()
        await health.stop_health_server()

        from src.rules_lawyer_bot.utils.observability import shutdown_langfuse

        shutdown_langfuse()

    application.post_shutdown = on_shutdown

    # TypeHandler in group=-1 marks "we received an update from Telegram" —
    # answers the liveness question "is polling actually working?" without
    # waiting for a real user message to go through the full pipeline.
    application.add_handler(
        TypeHandler(Update, _track_update, block=False), group=-1
    )

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

    # Last-resort error handler — forwards unhandled exceptions to Sentry
    application.add_error_handler(on_error)

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
