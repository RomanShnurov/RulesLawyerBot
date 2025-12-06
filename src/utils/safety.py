"""Safety mechanisms: rate limiting, error handling, resource management."""
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from typing import Callable, TypeVar

from src.config import settings
from src.utils.logger import logger

F = TypeVar('F', bound=Callable)


# ============================================
# Rate Limiting (In-Memory for MVP)
# ============================================

class InMemoryRateLimiter:
    """In-memory rate limiter for single-instance deployments.

    For multi-instance deployments, migrate to Redis-based implementation.
    """

    def __init__(
        self,
        max_requests: int = settings.max_requests_per_minute,
        window_seconds: int = 60
    ):
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per window
            window_seconds: Time window in seconds
        """
        self._requests: dict[int, list[datetime]] = defaultdict(list)
        self._max_requests = max_requests
        self._window = timedelta(seconds=window_seconds)
        self._lock = asyncio.Lock()

    async def check_rate_limit(self, user_id: int) -> tuple[bool, str]:
        """Check if user has exceeded rate limit.

        Args:
            user_id: Telegram user ID

        Returns:
            Tuple of (allowed: bool, message: str)
        """
        async with self._lock:
            now = datetime.now()
            cutoff = now - self._window

            # Clean old requests
            self._requests[user_id] = [
                ts for ts in self._requests[user_id]
                if ts > cutoff
            ]

            # Check limit
            if len(self._requests[user_id]) >= self._max_requests:
                wait_time = int((self._requests[user_id][0] - cutoff).total_seconds())
                return False, f"Rate limit exceeded. Please wait {wait_time}s"

            # Record new request
            self._requests[user_id].append(now)
            return True, ""


# Global rate limiter instance
rate_limiter = InMemoryRateLimiter()


# ============================================
# Resource Management (Semaphore for ugrep)
# ============================================

# Global semaphore to limit concurrent ugrep processes
ugrep_semaphore = asyncio.Semaphore(settings.max_concurrent_searches)


# ============================================
# Error Handling
# ============================================

class BotError(Exception):
    """User-facing error with separate logging details."""

    def __init__(self, user_message: str, log_details: str = None):
        """Initialize error.

        Args:
            user_message: Message shown to user (simple, friendly)
            log_details: Detailed error for logs (technical)
        """
        self.user_message = user_message
        self.log_details = log_details or user_message
        super().__init__(self.log_details)


def safe_execution(func: F) -> F:
    """Decorator for user-friendly error handling in tools.

    Catches exceptions and converts them to user-friendly messages
    while logging full details for debugging.

    Args:
        func: Function to wrap

    Returns:
        Wrapped function
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)

        except asyncio.TimeoutError:
            error_msg = (
                "⏱️ Operation timed out. "
                "Please try more specific search terms."
            )
            logger.warning(f"Timeout in {func.__name__}: {args}")
            return error_msg

        except FileNotFoundError as e:
            filename = str(e).split("'")[1] if "'" in str(e) else "unknown"
            error_msg = (
                f"📁 File not found: {filename}\n"
                f"Please check the game name and try again."
            )
            logger.error(f"File not found in {func.__name__}: {e}")
            return error_msg

        except PermissionError as e:
            error_msg = "🔒 Permission denied. Please contact administrator."
            logger.error(f"Permission error in {func.__name__}: {e}")
            return error_msg

        except BotError as e:
            # User-facing error, already formatted
            logger.error(f"Bot error in {func.__name__}: {e.log_details}")
            return e.user_message

        except Exception:
            # Unexpected error
            logger.exception(f"Unexpected error in {func.__name__}")
            return (
                "❌ Something went wrong. "
                "Please try again or contact support if the issue persists."
            )

    return wrapper
