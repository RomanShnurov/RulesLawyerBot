"""Centralized logging configuration."""
import logging
import sys
from pathlib import Path

from src.config import settings


def setup_logging() -> logging.Logger:
    """Configure application logging with file and console handlers."""

    # Create logger
    logger = logging.getLogger("boardgame_bot")
    logger.setLevel(getattr(logging, settings.log_level.upper()))

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s"
    )
    simple_formatter = logging.Formatter(
        "%(levelname)s: %(message)s"
    )

    # Console handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    logger.addHandler(console_handler)

    # File handler
    log_file = Path(settings.data_path) / "app.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    logger.addHandler(file_handler)

    # Reduce noise from external libraries
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger.info("Logging initialized")
    return logger


# Global logger instance
logger = setup_logging()
