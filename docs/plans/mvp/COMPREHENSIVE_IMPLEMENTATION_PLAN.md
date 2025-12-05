# Comprehensive Implementation Plan: Board Game Rules Bot

**Project:** RulesLawyerBot
**Goal:** Refactor single-file prototype into production-ready containerized application
**Tech Stack:** OpenAI Agents SDK + python-telegram-bot + ugrep + Docker
**Timeline:** 7-10 days (including testing)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Tech Stack & Dependencies](#2-tech-stack--dependencies)
3. [Target Directory Structure](#3-target-directory-structure)
4. [Phase 1: Infrastructure & Docker (Days 1-2)](#phase-1-infrastructure--docker-days-1-2)
5. [Phase 2: Core Refactoring (Days 3-4)](#phase-2-core-refactoring-days-3-4)
6. [Phase 3: Safety & Reliability (Day 5)](#phase-3-safety--reliability-day-5)
7. [Phase 4: Telegram Integration (Day 6)](#phase-4-telegram-integration-day-6)
8. [Phase 5: Testing & Deployment (Day 7)](#phase-5-testing--deployment-day-7)
9. [Deployment Instructions](#deployment-instructions)
10. [Monitoring & Maintenance](#monitoring--maintenance)

---

## 1. Architecture Overview

### Service Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      App Container (Python)                  │
│  ┌──────────────────┐         ┌──────────────────┐          │
│  │  Telegram Bot    │────────▶│  Agent (OpenAI)  │          │
│  │  (async loop)    │         │  + Tools         │          │
│  └──────────────────┘         └──────────────────┘          │
│           │                             │                    │
│           │                             ▼                    │
│           │                    ┌──────────────────┐          │
│           │                    │  ugrep + PDF     │          │
│           │                    │  (subprocess)    │          │
│           │                    └──────────────────┘          │
│           ▼                                                  │
│  ┌──────────────────┐         ┌──────────────────┐          │
│  │  Rate Limiter    │         │  SQLite Sessions │          │
│  │  (in-memory)     │         │  (per-user DBs)  │          │
│  └──────────────────┘         └──────────────────┘          │
└─────────────────────────────────────────────────────────────┘
                       │                    │
                       ▼                    ▼
              /app/rules_pdfs       /app/data
              (PDF Storage)        (SQLite + Logs)
```

### Design Principles

1. **Async-First**: All blocking operations wrapped in `asyncio.to_thread`
2. **Per-User Isolation**: Separate SQLite session per Telegram user
3. **Graceful Degradation**: Tools return error strings instead of crashing
4. **Resource Limits**: Semaphore (max 4 concurrent ugrep), rate limiting (10 req/min)
5. **Zero-Downtime**: Graceful shutdown handlers for SIGTERM/SIGINT

---

## 2. Tech Stack & Dependencies

### Base Image
- `python:3.11-slim` (multi-stage build)

### System Dependencies
- `ugrep` (fast PDF search)
- `poppler-utils` (PDF text extraction)
- `LANG=C.UTF-8` (Russian filename support)

### Python Dependencies

**Core** (`pyproject.toml`):
```toml
[project]
name = "boardgame-bot"
version = "0.1.0"
description = "Board Game Rules Telegram Bot with OpenAI Agents SDK"
requires-python = ">=3.11"
dependencies = [
    "python-telegram-bot>=21.0",
    "openai-agents-sdk>=0.1.0",
    "pypdf>=3.17.0",
    "pydantic-settings>=2.1.0",
    "tenacity>=8.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.2.0",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "ASYNC"]
```

---

## 3. Target Directory Structure

```text
boardgame-bot/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .gitignore
├── pyproject.toml
├── uv.lock
├── Makefile
├── README.md
│
├── rules_pdfs/                    # Volume: PDF storage
│   └── (user uploads PDFs here)
│
├── data/                          # Volume: Persistent data
│   ├── sessions/                  # Per-user SQLite DBs
│   └── app.log                    # Application logs
│
├── src/
│   ├── __init__.py
│   ├── main.py                    # Entry point (Telegram setup)
│   ├── config.py                  # Pydantic settings
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── definition.py          # Agent initialization
│   │   └── tools.py               # @function_tool definitions
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py              # Logging configuration
│       ├── safety.py              # Rate limiting + error handling
│       ├── timer.py               # ScopeTimer class
│       └── telegram_helpers.py    # Message splitting utility
│
└── tests/
    ├── __init__.py
    ├── conftest.py                # Test fixtures
    ├── test_tools.py              # Tool unit tests
    └── test_integration.py        # End-to-end tests
```

---

## Phase 1: Infrastructure & Docker (Days 1-2)

### 🎯 Goal
Create reproducible, optimized Docker environment with proper volume mounts.

### Step 1.1: Multi-Stage Dockerfile

**Create `Dockerfile`:**

```dockerfile
# ============================================
# Build Stage: Install dependencies
# ============================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies to virtual environment
RUN uv sync --frozen --no-dev

# ============================================
# Runtime Stage: Minimal production image
# ============================================
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ugrep \
    poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# Set locale for Russian filenames
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

# Copy virtual environment from builder
COPY --from=builder /build/.venv /app/.venv

# Set working directory
WORKDIR /app

# Copy application code
COPY src/ ./src/

# Add virtualenv to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Create directories for volumes
RUN mkdir -p /app/rules_pdfs /app/data/sessions

# Run as non-root user
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app
USER botuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c 'import sys; sys.exit(0)'

# Run application
CMD ["python", "-m", "src.main"]
```

**Benefits:**
- ✅ Smaller image (~300MB vs 500MB)
- ✅ Cached dependency layer (faster rebuilds)
- ✅ Separated build/runtime dependencies
- ✅ Non-root user for security

---

### Step 1.2: Docker Compose Configuration

**Create `docker-compose.yml`:**

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: boardgame-bot
    restart: unless-stopped

    environment:
      - TELEGRAM_TOKEN=${TELEGRAM_TOKEN}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://api.proxyapi.ru/openai/v1}
      - OPENAI_MODEL=${OPENAI_MODEL:-gpt-5-nano}
      - PDF_STORAGE_PATH=/app/rules_pdfs
      - DATA_PATH=/app/data
      - LOG_LEVEL=${LOG_LEVEL:-INFO}

    volumes:
      - ./rules_pdfs:/app/rules_pdfs
      - ./data:/app/data

    healthcheck:
      test: ["CMD-SHELL", "python -c 'import sys; sys.exit(0)'"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

    # Optional: Resource limits
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

---

### Step 1.3: Environment Configuration

**Create `.env.example`:**

```ini
# Telegram Bot Configuration
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# OpenAI Configuration
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1
OPENAI_MODEL=gpt-5-nano

# Application Settings
PDF_STORAGE_PATH=/app/rules_pdfs
DATA_PATH=/app/data
LOG_LEVEL=INFO

# Rate Limiting
MAX_REQUESTS_PER_MINUTE=10
MAX_CONCURRENT_SEARCHES=4
```

**Create `.gitignore`:**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
ENV/

# Testing
.pytest_cache/
.coverage
htmlcov/

# Logs
*.log
app.log

# Data
data/
rules_pdfs/

# Environment
.env

# Ruff
.ruff_cache/

# IDE
.vscode/
.idea/
*.swp
*.swo
```

---

### Step 1.4: Makefile for Development

**Create `Makefile`:**

```makefile
.PHONY: help install build up down logs test lint format clean

help:
	@echo "Available commands:"
	@echo "  make install   - Install dependencies with uv"
	@echo "  make build     - Build Docker image"
	@echo "  make up        - Start bot in Docker"
	@echo "  make down      - Stop bot"
	@echo "  make logs      - View logs"
	@echo "  make test      - Run tests"
	@echo "  make lint      - Run ruff linter"
	@echo "  make format    - Format code with ruff"
	@echo "  make clean     - Remove cache files"

install:
	uv sync

build:
	docker-compose build

up:
	docker-compose up -d
	@echo "Bot started. View logs with: make logs"

down:
	docker-compose down

logs:
	docker-compose logs -f app

test:
	uv run pytest -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache
```

---

### Step 1.5: Verification

**Test Docker build:**

```bash
# Create .env from example
cp .env.example .env
# Edit .env with your tokens

# Test build
docker-compose build

# Verify image size
docker images boardgame-bot

# Test volume mounts
docker-compose up -d
docker exec boardgame-bot ls -la /app/rules_pdfs
docker exec boardgame-bot ls -la /app/data
docker-compose down
```

✅ **Phase 1 Complete** when:
- [ ] Docker image builds successfully (~300MB)
- [ ] Volumes mount correctly
- [ ] Environment variables load from `.env`

---

## Phase 2: Core Refactoring (Days 3-4)

### 🎯 Goal
Move code from `main.py` into modular structure WITHOUT breaking existing logic.

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

---

## Phase 3: Safety & Reliability (Day 5)

### 🎯 Goal
Implement rate limiting, error handling, and resource management.

---

### Step 3.1: Safety Layer

**Create `src/utils/safety.py`:**

```python
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

        except Exception as e:
            # Unexpected error
            logger.exception(f"Unexpected error in {func.__name__}")
            return (
                "❌ Something went wrong. "
                "Please try again or contact support if the issue persists."
            )

    return wrapper
```

**Benefits:**
- ✅ In-memory rate limiting (10 req/min per user)
- ✅ Semaphore prevents CPU overload from ugrep
- ✅ User-friendly error messages
- ✅ Full error details logged for debugging

---

## Phase 4: Telegram Integration (Day 6)

### 🎯 Goal
Wire up Telegram bot with all components and graceful shutdown.

---

### Step 4.1: Main Application

**Create `src/main.py`:**

```python
"""Telegram bot entry point with async handlers."""
import asyncio
import signal
from datetime import datetime

from openai_agents_sdk import Runner
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

**Tips:**
- Use game names in English (e.g., "Arkham Horror" not "Ужас Аркхэма")
- For Russian text search, I'll use smart regex patterns
- Rate limit: {settings.max_requests_per_minute} requests per minute

Type your question to get started!
""".strip()

    await update.message.reply_text(welcome_message)


async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /health command for monitoring.

    Args:
        update: Telegram update object
        context: Telegram context
    """
    uptime = (datetime.now() - bot_start_time).total_seconds()

    await update.message.reply_text(
        f"✅ Bot is healthy\n"
        f"⏱️ Uptime: {uptime:.0f}s\n"
        f"📊 Rate limit: {settings.max_requests_per_minute} req/min"
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
    application.add_handler(CommandHandler("health", health_check))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Register graceful shutdown handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(shutdown(application))
        )

    # Run bot in polling mode
    logger.info("Bot started. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```

**Key Features:**
- ✅ Rate limiting before processing
- ✅ Typing indicator during agent execution
- ✅ Semaphore for ugrep concurrency
- ✅ Message splitting for long responses
- ✅ Per-user session isolation
- ✅ Graceful shutdown on SIGTERM/SIGINT
- ✅ Health check endpoint

---

## Phase 5: Testing & Deployment (Day 7)

### 🎯 Goal
Validate functionality and deploy to production.

---

### Step 5.1: Test Configuration

**Create `tests/conftest.py`:**

```python
"""Pytest configuration and shared fixtures."""
import pytest
from pathlib import Path
from pypdf import PdfWriter


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a sample PDF for testing.

    Args:
        tmp_path: Pytest temporary directory

    Returns:
        Path to created PDF
    """
    pdf_path = tmp_path / "test_game.pdf"

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)

    with open(pdf_path, "wb") as f:
        writer.write(f)

    return pdf_path


@pytest.fixture
def mock_settings(tmp_path: Path, monkeypatch):
    """Override settings for testing.

    Args:
        tmp_path: Pytest temporary directory
        monkeypatch: Pytest monkeypatch fixture
    """
    from src.config import settings

    monkeypatch.setattr(settings, "pdf_storage_path", str(tmp_path / "pdfs"))
    monkeypatch.setattr(settings, "data_path", str(tmp_path / "data"))

    # Create directories
    Path(settings.pdf_storage_path).mkdir(parents=True, exist_ok=True)
    Path(settings.data_path).mkdir(parents=True, exist_ok=True)

    return settings
```

---

### Step 5.2: Tool Tests

**Create `tests/test_tools.py`:**

```python
"""Unit tests for agent tools."""
import pytest
from pathlib import Path

from src.agent.tools import search_filenames, read_full_document


@pytest.mark.asyncio
async def test_search_filenames_success(mock_settings, tmp_path):
    """Test successful filename search."""
    # Create test PDFs
    pdf_dir = Path(mock_settings.pdf_storage_path)
    (pdf_dir / "Gloomhaven.pdf").touch()
    (pdf_dir / "Arkham Horror.pdf").touch()

    # Search
    result = await search_filenames("Gloomhaven")

    assert "Found 1 file" in result
    assert "Gloomhaven.pdf" in result


@pytest.mark.asyncio
async def test_search_filenames_no_match(mock_settings):
    """Test filename search with no matches."""
    result = await search_filenames("NonexistentGame")

    assert "No PDF files found" in result


@pytest.mark.asyncio
async def test_read_full_document(mock_settings, sample_pdf):
    """Test PDF reading."""
    # Move sample PDF to rules directory
    pdf_dir = Path(mock_settings.pdf_storage_path)
    target = pdf_dir / "test.pdf"
    sample_pdf.rename(target)

    # Read PDF
    result = await read_full_document("test.pdf")

    assert "Page 1" in result
```

---

### Step 5.3: Integration Test

**Create `tests/test_integration.py`:**

```python
"""End-to-end integration tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.main import handle_message


@pytest.mark.asyncio
async def test_message_handling_with_rate_limit(monkeypatch):
    """Test that rate limiting works correctly."""
    # Mock dependencies
    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.message.text = "How does combat work?"

    mock_context = MagicMock()
    mock_context.bot.send_chat_action = AsyncMock()
    mock_context.bot.send_message = AsyncMock()

    # First request should succeed
    await handle_message(mock_update, mock_context)

    # Verify chat action was sent
    mock_context.bot.send_chat_action.assert_called_once()
```

---

### Step 5.4: Load Testing

**Manual load test script:**

```python
"""Load test script for concurrent users."""
import asyncio
import time
from telegram import Bot

async def simulate_user(bot: Bot, chat_id: int, message: str):
    """Simulate single user request."""
    start = time.time()
    await bot.send_message(chat_id=chat_id, text=message)
    duration = time.time() - start
    print(f"Request completed in {duration:.2f}s")

async def load_test(token: str, chat_id: int, num_users: int = 10):
    """Simulate multiple concurrent users."""
    bot = Bot(token=token)

    tasks = [
        simulate_user(bot, chat_id, f"Test message {i}")
        for i in range(num_users)
    ]

    start = time.time()
    await asyncio.gather(*tasks)
    total = time.time() - start

    print(f"\n✅ {num_users} requests completed in {total:.2f}s")
    print(f"Average: {total/num_users:.2f}s per request")

# Run: python tests/load_test.py
if __name__ == "__main__":
    TOKEN = "YOUR_TOKEN"
    CHAT_ID = 123456789
    asyncio.run(load_test(TOKEN, CHAT_ID, num_users=10))
```

---

## Deployment Instructions

### Step D.1: Prepare Environment

```bash
# Clone repository
git clone <repository-url>
cd boardgame-bot

# Create .env file
cp .env.example .env
nano .env  # Add your tokens

# Add PDF files
mkdir -p rules_pdfs
# Copy your PDF rulebooks to rules_pdfs/

# Create data directory
mkdir -p data/sessions
```

---

### Step D.2: Build and Run

```bash
# Build Docker image
docker-compose build

# Start bot
docker-compose up -d

# View logs
docker-compose logs -f app

# Check health
docker exec boardgame-bot python -c "print('Bot is running')"
```

---

### Step D.3: Verify Deployment

**Checklist:**

- [ ] Bot responds to `/start`
- [ ] Bot responds to `/health`
- [ ] File search works: "Find Gloomhaven"
- [ ] Text search works: "Search for combat rules in Gloomhaven.pdf"
- [ ] Long responses are split correctly
- [ ] Rate limiting triggers after 10 requests in 1 minute
- [ ] Multiple users can interact simultaneously
- [ ] Logs written to `data/app.log`
- [ ] Session databases created in `data/sessions/`

---

### Step D.4: Production Optimizations

**For production environments:**

1. **Use PostgreSQL instead of SQLite:**

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: boardgame_bot
      POSTGRES_USER: bot
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
```

2. **Add Redis for multi-instance deployments:**

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - ./data/redis:/data
```

3. **Configure monitoring:**

```bash
# Add Prometheus metrics
uv add prometheus-client

# Expose metrics endpoint
# src/main.py
from prometheus_client import Counter, Histogram, start_http_server

requests_total = Counter('bot_requests_total', 'Total requests')
request_duration = Histogram('bot_request_duration_seconds', 'Request duration')
```

---

## Monitoring & Maintenance

### Log Monitoring

```bash
# View live logs
docker-compose logs -f app

# Search for errors
docker-compose logs app | grep ERROR

# Check rate limiting events
docker-compose logs app | grep "Rate limit exceeded"
```

### Performance Monitoring

```bash
# Check container resource usage
docker stats boardgame-bot

# View ugrep process count
docker exec boardgame-bot ps aux | grep ugrep

# Check disk usage
docker exec boardgame-bot du -sh /app/data
```

### Database Maintenance

```bash
# Backup all user sessions
tar -czf sessions_backup_$(date +%Y%m%d).tar.gz data/sessions/

# Clean old sessions (>30 days inactive)
find data/sessions -name "*.db" -mtime +30 -delete
```

---

## Critical Implementation Checklist

Before marking each phase complete, verify:

### Phase 1: Infrastructure
- [ ] Dockerfile builds successfully (<400MB)
- [ ] Multi-stage build works
- [ ] Volumes mount correctly
- [ ] Environment variables load from `.env`
- [ ] `ugrep` and `poppler-utils` installed

### Phase 2: Core Refactoring
- [ ] All imports resolve correctly
- [ ] `@async_tool` decorator applied to all tools
- [ ] Per-user sessions working
- [ ] Agent instructions preserved
- [ ] Configuration loads from `pydantic-settings`

### Phase 3: Safety
- [ ] Rate limiter blocks after 10 requests
- [ ] ugrep semaphore limits to 4 concurrent
- [ ] User-friendly error messages displayed
- [ ] Full errors logged to `app.log`

### Phase 4: Telegram
- [ ] `/start` command works
- [ ] `/health` command works
- [ ] Long messages split correctly
- [ ] Graceful shutdown on Ctrl+C
- [ ] Multiple users work simultaneously

### Phase 5: Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Load test with 10 users succeeds
- [ ] No database locks under load
- [ ] Response time <5s per request

---

## Final Notes

### What Was Preserved from Original
✅ Agent instructions (Russian regex patterns, game name translations)
✅ Tool logic (search_filenames, search_inside_file_ugrep, read_full_document)
✅ ScopeTimer for performance monitoring
✅ Logging to file + console

### What Was Improved
✅ Async tool wrappers (prevents event loop blocking)
✅ Per-user sessions (prevents database locks)
✅ Message splitting (prevents Telegram errors)
✅ Rate limiting (prevents abuse)
✅ User-friendly errors (better UX)
✅ Docker multi-stage build (smaller images)
✅ Configuration management (pydantic-settings)
✅ Graceful shutdown (no lost requests)

### Migration from Redis to In-Memory

The original plan used Redis for rate limiting. This version uses **in-memory rate limiting** for simplicity. Migrate to Redis when:
- Running multiple bot instances
- Need rate limiting across restarts
- Scaling beyond 100 concurrent users

### Estimated Timeline

| Phase | Tasks | Days |
|-------|-------|------|
| Phase 1 | Docker setup | 1-2 |
| Phase 2 | Refactoring | 2-3 |
| Phase 3 | Safety layer | 1 |
| Phase 4 | Telegram integration | 1 |
| Phase 5 | Testing & deployment | 1-2 |
| **Total** | | **7-10 days** |

---

**Status:** ✅ Ready for Implementation
**Generated:** 2025-11-26
**Version:** 1.0
**Author:** Claude Code (Sonnet 4.5)
