"""Centralized logging configuration."""

import logging
import sys
from pathlib import Path

from src.rules_lawyer_bot.config import settings


def setup_logging() -> logging.Logger:
    """Configure application logging with file and console handlers."""

    # Create logger
    logger = logging.getLogger("boardgame_bot")
    logger.setLevel(getattr(logging, settings.log_level.upper()))

    # Create formatter
    detailed_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s"
    )

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(detailed_formatter)
    logger.addHandler(console_handler)

    # File handler
    try:
        log_file = Path(settings.data_path) / "app.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        logger.addHandler(file_handler)

        logger.info(f"Logging initialized - Log file: {log_file.absolute()}")
    except Exception as e:
        logger.warning(f"Failed to create log file at {log_file}: {e}")
        logger.warning("Continuing with console logging only")

    # Reduce noise from external libraries
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Suppress OpenTelemetry/Logfire trace logs
    logging.getLogger("logfire").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry.sdk.trace").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry.exporter").setLevel(logging.WARNING)

    return logger


# Global logger instance
logger = setup_logging()
