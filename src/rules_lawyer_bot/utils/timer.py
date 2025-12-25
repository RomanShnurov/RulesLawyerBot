"""Performance measurement utilities."""
import time
from contextlib import contextmanager
from typing import Generator

from src.rules_lawyer_bot.utils.logger import logger


class ScopeTimer:
    """Context manager for measuring execution time."""

    def __init__(self, description: str):
        """Initialize timer with description.

        Args:
            description: Human-readable description of the operation
        """
        self.description = description
        self.start_time: float = 0
        self.end_time: float = 0

    def __enter__(self) -> "ScopeTimer":
        """Start timer."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop timer and log duration."""
        self.end_time = time.time()
        duration = self.end_time - self.start_time
        logger.info(f"{self.description} took {duration:.2f} seconds")


@contextmanager
def measure_time(operation: str) -> Generator[None, None, None]:
    """Simple timer context manager.

    Usage:
        with measure_time("Database query"):
            # ... operation ...

    Args:
        operation: Name of the operation being timed
    """
    start = time.time()
    try:
        yield
    finally:
        duration = time.time() - start
        logger.debug(f"{operation} completed in {duration:.3f}s")
