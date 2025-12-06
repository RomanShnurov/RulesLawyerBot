## Phase 2: Core Refactoring (Days 3-4) ✅ COMPLETED

### 🎯 Goal
Move code from `src/main.py` into modular structure WITHOUT breaking existing logic.

---

### Step 2.1: Configuration Management

**Create `src/config.py`:**

```python
"""Application configuration using pydantic-settings."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    # Telegram
    telegram_token: str = Field(..., description="Telegram bot token")

    # OpenAI
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_base_url: str = Field(
        default="https://api.proxyapi.ru/openai/v1",
        description="OpenAI API base URL"
    )
    openai_model: str = Field(
        default="gpt-5-nano",
        description="OpenAI model name"
    )

    # Paths
    pdf_storage_path: str = Field(
        default="./rules_pdfs",
        description="Directory containing PDF rulebooks"
    )
    data_path: str = Field(
        default="./data",
        description="Directory for SQLite DBs and logs"
    )

    # Performance
    max_requests_per_minute: int = Field(
        default=10,
        description="Max requests per user per minute"
    )
    max_concurrent_searches: int = Field(
        default=4,
        description="Max concurrent ugrep processes"
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )

    @property
    def session_db_dir(self) -> str:
        """Directory for per-user session databases."""
        return f"{self.data_path}/sessions"


# Global settings instance
settings = Settings()
```

---

### Step 2.2: Logging Setup

**Create `src/utils/logger.py`:**

```python
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
```

---

### Step 2.3: Performance Timer

**Create `src/utils/timer.py`:**

```python
"""Performance measurement utilities."""
import time
from contextlib import contextmanager
from typing import Generator

from src.utils.logger import logger


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
```

---

### Step 2.4: Telegram Helper Functions

**Create `src/utils/telegram_helpers.py`:**

```python
"""Telegram-specific utility functions."""
from telegram import Bot

from src.utils.logger import logger


async def send_long_message(
    bot: Bot,
    chat_id: int,
    text: str,
    max_length: int = 4000
) -> None:
    """Split and send long messages to avoid Telegram's 4096 char limit.

    Splits on newlines to preserve formatting and avoid breaking code blocks.

    Args:
        bot: Telegram bot instance
        chat_id: Target chat ID
        text: Message text (may exceed 4096 chars)
        max_length: Maximum length per message (default: 4000 for safety)
    """
    if len(text) <= max_length:
        await bot.send_message(chat_id=chat_id, text=text)
        return

    # Smart splitting: preserve paragraphs and code blocks
    chunks = []
    current_chunk = ""

    for line in text.split('\n'):
        # Check if adding this line would exceed limit
        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ('\n' if current_chunk else '') + line

    # Add remaining chunk
    if current_chunk:
        chunks.append(current_chunk)

    # Send chunks with indicators
    logger.info(f"Splitting message into {len(chunks)} parts")
    for i, chunk in enumerate(chunks, 1):
        prefix = f"[Part {i}/{len(chunks)}]\n" if len(chunks) > 1 else ""
        await bot.send_message(chat_id=chat_id, text=prefix + chunk)
```

---

### Step 2.5: Agent Tools (CRITICAL: Async Wrapper)

**Create `src/agent/tools.py`:**

```python
"""Agent tool functions with async wrappers for blocking operations."""
import asyncio
import subprocess
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

from openai_agents_sdk import function_tool
from pypdf import PdfReader

from src.config import settings
from src.utils.logger import logger
from src.utils.timer import ScopeTimer

# Type variable for decorator
F = TypeVar('F', bound=Callable)


def async_tool(func: F) -> F:
    """Decorator to run synchronous tool functions in thread pool.

    CRITICAL: This prevents blocking the Telegram asyncio event loop
    when calling subprocess.run() or other blocking I/O.

    Args:
        func: Synchronous function to wrap

    Returns:
        Async function that runs in thread pool
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)
    return wrapper


@function_tool
@async_tool
def search_filenames(query: str) -> str:
    """Search for PDF files by filename in the rules library.

    Args:
        query: Search term (game name or part of filename)

    Returns:
        List of matching filenames or error message
    """
    with ScopeTimer(f"search_filenames('{query}')"):
        try:
            pdf_dir = Path(settings.pdf_storage_path)
            if not pdf_dir.exists():
                return f"Error: PDF directory not found at {pdf_dir}"

            # Case-insensitive search
            query_lower = query.lower()
            matches = [
                f.name for f in pdf_dir.glob("*.pdf")
                if query_lower in f.name.lower()
            ]

            if not matches:
                return f"No PDF files found matching '{query}'"

            # Limit results to avoid token overflow
            if len(matches) > 50:
                matches = matches[:50]
                return (
                    f"Found {len(matches)}+ files (showing first 50):\n" +
                    "\n".join(matches)
                )

            return f"Found {len(matches)} file(s):\n" + "\n".join(matches)

        except Exception as e:
            logger.exception(f"Error in search_filenames: {e}")
            return f"Error searching files: {str(e)}"


@function_tool
@async_tool
def search_inside_file_ugrep(filename: str, keywords: str) -> str:
    """Search inside a PDF file using ugrep for fast regex matching.

    Args:
        filename: Name of the PDF file (must exist in rules_pdfs/)
        keywords: Search keywords or regex pattern

    Returns:
        Matching text snippets or error message
    """
    with ScopeTimer(f"search_inside_file_ugrep('{filename}', '{keywords}')"):
        try:
            pdf_path = Path(settings.pdf_storage_path) / filename
            if not pdf_path.exists():
                return f"Error: File '{filename}' not found"

            # Run ugrep with PDF filter
            # -i: case insensitive
            # --filter: convert PDF to text on-the-fly
            # -C 2: show 2 lines of context
            result = subprocess.run(
                [
                    "ugrep",
                    "-i",  # Case insensitive
                    "--filter=pdf:pdftotext - -",  # PDF text extraction
                    "-C", "2",  # 2 lines of context
                    keywords,
                    str(pdf_path)
                ],
                capture_output=True,
                text=True,
                timeout=30  # Prevent hanging
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                # Truncate to avoid token overflow
                if len(output) > 10000:
                    output = output[:10000] + "\n...(truncated)"
                return output if output else "No matches found"

            elif result.returncode == 1:
                return "No matches found"

            else:
                error = result.stderr.strip()
                logger.error(f"ugrep error: {error}")
                return f"Search error: {error}"

        except subprocess.TimeoutExpired:
            return "Search timed out (>30s). Please try more specific keywords."

        except FileNotFoundError:
            return (
                "Error: 'ugrep' tool not installed. "
                "Please install: apt-get install ugrep (Linux) or brew install ugrep (macOS)"
            )

        except Exception as e:
            logger.exception(f"Error in search_inside_file_ugrep: {e}")
            return f"Search failed: {str(e)}"


@function_tool
@async_tool
def read_full_document(filename: str) -> str:
    """Fallback: Read entire PDF content using pypdf library.

    Use this when ugrep fails or is unavailable.

    Args:
        filename: Name of the PDF file

    Returns:
        Full text content (truncated to 100k chars) or error message
    """
    with ScopeTimer(f"read_full_document('{filename}')"):
        try:
            pdf_path = Path(settings.pdf_storage_path) / filename
            if not pdf_path.exists():
                return f"Error: File '{filename}' not found"

            reader = PdfReader(pdf_path)
            text_parts = []

            for page_num, page in enumerate(reader.pages, 1):
                text_parts.append(f"--- Page {page_num} ---\n")
                text_parts.append(page.extract_text())

            full_text = "\n".join(text_parts)

            # Truncate to avoid context overflow
            if len(full_text) > 100000:
                full_text = full_text[:100000] + "\n...(truncated at 100k chars)"

            return full_text

        except Exception as e:
            logger.exception(f"Error in read_full_document: {e}")
            return f"Failed to read PDF: {str(e)}"
```

**⚠️ CRITICAL NOTE:** The `@async_tool` decorator is **MANDATORY** to prevent blocking the Telegram bot's event loop!

---

### Step 2.6: Agent Definition

**Create `src/agent/definition.py`:**

```python
"""OpenAI Agent definition and session management."""
from pathlib import Path

from openai import AsyncOpenAI
from openai_agents_sdk import Agent, OpenAIChatCompletionsModel, SQLiteSession, set_tracing_disabled

from src.agent.tools import read_full_document, search_filenames, search_inside_file_ugrep
from src.config import settings
from src.utils.logger import logger

# Disable tracing for production
set_tracing_disabled(disabled=True)


def create_agent() -> Agent:
    """Create the board game referee agent with tools.

    Returns:
        Configured Agent instance
    """
    # Initialize OpenAI client with custom base URL
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url
    )

    model = OpenAIChatCompletionsModel(
        client=client,
        model=settings.openai_model
    )

    # Agent instructions (PRESERVED from original implementation)
    instructions = """
You are a Board Game Referee bot.

**Tools:**
1. `search_filenames(query)` - Find PDF files by game name
2. `search_inside_file_ugrep(filename, keywords)` - Fast regex search inside PDF
3. `read_full_document(filename)` - Read entire PDF (fallback)

**Rules for filename search:**
- PDF files are named using **ORIGINAL ENGLISH** game titles
- If user provides localized name (e.g., Russian "Схватка в стиле фэнтези"),
  translate to English ("Super Fantasy Brawl") before searching
- Use internal knowledge of popular game names

**Rules for text search (Russian language):**
- Use **REGEX patterns with word roots and synonyms** due to complex morphology
- Example: For "movement" use: `перемещ|движен|ход|бег`
- Example: For "attack" use: `атак|удар|бой|сраж`
- This handles: перемещение, переместить, движение, передвижение, ход, etc.

**Response format:**
1. Acknowledge the question
2. Use tools to find information
3. Provide clear, cited answer with page numbers if available
4. If information not found, suggest checking specific sections or offer general knowledge

**Internal game knowledge:**
Store common game name translations:
- "Схватка в стиле фэнтези" → "Super Fantasy Brawl"
- "Время приключений" → "Time of Adventure"
- "Ужас Аркхэма" → "Arkham Horror"
(Expand as needed)
""".strip()

    agent = Agent(
        name="Board Game Referee",
        model=model,
        instructions=instructions,
        tools=[
            search_filenames,
            search_inside_file_ugrep,
            read_full_document
        ]
    )

    logger.info("Agent created successfully")
    return agent


def get_user_session(user_id: int) -> SQLiteSession:
    """Get or create SQLite session for a specific user.

    IMPORTANT: Each user gets isolated session to prevent database locks.

    Args:
        user_id: Telegram user ID

    Returns:
        SQLiteSession instance for this user
    """
    session_dir = Path(settings.session_db_dir)
    session_dir.mkdir(parents=True, exist_ok=True)

    session_id = f"conversation_{user_id}"
    db_path = session_dir / f"{user_id}.db"

    logger.debug(f"Loading session for user {user_id}: {db_path}")

    return SQLiteSession(
        session_id=session_id,
        db_path=str(db_path)
    )


# Global agent instance
rules_agent = create_agent()
```

**Key Changes from Original:**
1. ✅ Per-user sessions (no more shared `"conversation_roman"`)
2. ✅ Async OpenAI client
3. ✅ Preserved critical agent instructions
4. ✅ Clean separation of concerns
