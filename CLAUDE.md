# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RulesLawyerBot is a production-ready Telegram bot that acts as a board game rules referee, using OpenAI's Agents SDK to search through PDF rulebooks and answer questions in multiple languages.

**Key Features**: Async architecture, per-user session isolation, rate limiting, concurrent search control, comprehensive testing.

## Quick Commands

### Development
```bash
just install         # Install dependencies with uv
just run-local       # Run bot locally without Docker
just test            # Run tests with pytest
just lint            # Run ruff linter
just format          # Format code with ruff
```

### Docker Deployment
```bash
just build           # Build Docker image
just up              # Start bot in Docker (detached)
just down            # Stop bot
just logs            # View live logs
just restart         # Restart bot (down + up)
```

### Utilities
```bash
just setup           # Setup from scratch (creates .env, directories, installs deps)
just validate        # Validate Docker setup
just clean           # Remove cache files
```

**Note**: All commands also available via `make` (e.g., `make test`, `make build`).

## Documentation

**START HERE**: [docs/INDEX.md](docs/INDEX.md) - Complete documentation map

Key documentation:
- [docs/QUICKSTART.md](docs/QUICKSTART.md) - Getting started guide
- [docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md) - Docker deployment
- [docs/plans/mvp/overview.md](docs/plans/mvp/overview.md) - Architecture overview
- [docs/plans/next_steps.md](docs/plans/next_steps.md) - Future enhancements

## Architecture

### Modular Structure

```
src/
├── main.py                 # Telegram bot entry point (async handlers)
├── config.py               # Settings with pydantic-settings
├── agent/
│   ├── definition.py       # Agent creation & session management
│   └── tools.py            # Agent tools (@function_tool decorated)
└── utils/
    ├── logger.py           # Logging configuration
    ├── timer.py            # Performance monitoring (ScopeTimer)
    ├── safety.py           # Rate limiting, semaphore, error handling
    └── telegram_helpers.py # Message splitting utilities
```

### Key Components

**1. Configuration (src/config.py)**
- Uses `pydantic-settings` for type-safe configuration
- All settings loaded from `.env` file
- Properties: `session_db_dir`, `admin_ids`

**2. Agent System (src/agent/)**
- **definition.py**: Creates agent, manages per-user sessions
  - `create_agent()`: Returns configured `Agent` instance
  - `get_user_session(user_id)`: Returns isolated `SQLiteSession` per user
  - Agent instructions include multilingual search patterns
- **tools.py**: Agent tools decorated with `@function_tool`
  - `search_filenames(query)`: Find PDFs by game name
  - `search_inside_file_ugrep(filename, keywords)`: Fast regex search with ugrep
  - `read_full_document(filename)`: Fallback PDF reader (pypdf)

**3. Telegram Bot (src/main.py)**
- Async handlers: `start_command`, `get_my_id`, `health_check`, `handle_message`
- Rate limiting check before processing messages
- Sends "typing" action during processing
- Uses `send_long_message()` to handle responses >4000 chars
- Graceful shutdown with signal handling

**4. Utilities (src/utils/)**
- **logger.py**: Dual output (console + file), UTF-8 encoding
- **timer.py**: `ScopeTimer` context manager for performance monitoring
- **safety.py**: `rate_limiter` (per-user), `ugrep_semaphore` (concurrent search control)
- **telegram_helpers.py**: `send_long_message()` splits long responses

### Per-User Session Isolation

**IMPORTANT**: Each user has their own SQLite database to prevent database locks.

```python
# Session databases stored at:
{DATA_PATH}/sessions/user_{user_id}.db

# Created in src/agent/definition.py:
session = SQLiteSession(db_path=f"{settings.session_db_dir}/user_{user_id}.db")
```

### Rate Limiting & Resource Management

**Rate Limiting** (src/utils/safety.py):
- Default: 10 requests/minute per user
- In-memory tracking with `rate_limiter` dictionary
- Configure via `MAX_REQUESTS_PER_MINUTE` env var

**Concurrent Search Control**:
- `ugrep_semaphore` limits parallel ugrep processes (default: 4)
- Prevents resource exhaustion
- Configure via `MAX_CONCURRENT_SEARCHES` env var

### Agent Instructions Pattern

The agent has **specialized multilingual search logic** (src/agent/definition.py):

1. **Localized Game Name Translation**: PDFs named using **original English titles**
   - User says "Схватка в стиле фэнтези" → Agent translates to "Super Fantasy Brawl"

2. **Russian Morphology Handling**: Uses **regex patterns with word roots and synonyms**
   - Example: "movement" → `перемещ|движен|ход|бег`
   - Example: "attack" → `атак|удар|бой|сраж`

3. **Mandatory Tool Calling Workflow**:
   - Agent MUST call tools before outputting structured response
   - Sequence: `list_directory_tree()` → `search_filenames()` → `search_inside_file_ugrep()`
   - Instructions explicitly forbid predicting/guessing tool results

**IMPORTANT**: The Schema-Guided Reasoning (SGR) pattern with structured outputs requires a capable model. Small/fast models (like `gpt-3.5-turbo` or lightweight alternatives) may skip tool calls and predict results. **Recommended models**: `gpt-4o`, `gpt-4-turbo`, or `gpt-4` for reliable tool calling behavior.

## Configuration

All configuration via environment variables (loaded from `.env`):

### Required
- `TELEGRAM_TOKEN`: Bot token from @BotFather
- `OPENAI_API_KEY`: OpenAI API key

### Optional
- `OPENAI_BASE_URL`: API endpoint (default: `https://api.proxyapi.ru/openai/v1`)
- `OPENAI_MODEL`: Model name (default: `gpt-5-nano`)
- `PDF_STORAGE_PATH`: PDF directory (default: `./rules_pdfs`)
- `DATA_PATH`: Data directory (default: `./data`)
- `LOG_LEVEL`: Logging level (default: `INFO`)
- `MAX_REQUESTS_PER_MINUTE`: Rate limiting (default: `10`)
- `MAX_CONCURRENT_SEARCHES`: Concurrent search limit (default: `4`)
- `ADMIN_USER_IDS`: Comma-separated admin Telegram user IDs

See `src/config.py` for full configuration model.

## Common Modification Scenarios

### Adding New Agent Tools
1. Define function in `src/agent/tools.py` with type hints and docstring
2. Decorate with `@function_tool`
3. Import and add to `tools` list in `create_agent()` (src/agent/definition.py)

Example:
```python
# In src/agent/tools.py
@function_tool
def my_new_tool(param: str) -> str:
    """Tool description for the agent."""
    return result

# In src/agent/definition.py
from src.agent.tools import my_new_tool, search_filenames, ...
# Then add to Agent(tools=[search_filenames, ..., my_new_tool])
```

### Adding New Telegram Commands
1. Define async handler in `src/main.py`
2. Register with `application.add_handler(CommandHandler("command_name", handler))`

### Changing Rate Limits
- Modify `MAX_REQUESTS_PER_MINUTE` or `MAX_CONCURRENT_SEARCHES` in `.env`
- Or update defaults in `src/config.py`

### Supporting Additional Languages
Update agent instructions in `src/agent/definition.py` with:
- Language-specific search patterns
- Translation guidelines for filename searches
- Morphology handling rules

### Customizing Response Limits
- Message splitting threshold: `src/utils/telegram_helpers.py` (4000 chars)
- ugrep output: `src/agent/tools.py` (10,000 chars)
- Full document: `src/agent/tools.py` (100,000 chars)

## Docker

**CRITICAL**: Python version **must match** between Dockerfile and pyproject.toml:
- Current requirement: **Python 3.13**
- Dockerfile: `python:3.13-slim`

Build stages:
1. **Builder**: Installs dependencies with `uv sync --frozen --no-dev`
2. **Runtime**: Copies virtualenv, installs system deps (ugrep, poppler-utils), runs as non-root user

## Testing

Run tests with: `just test` or `pytest -v`

Test structure:
- **tests/test_tools.py**: Unit tests for agent tools
- **tests/test_integration.py**: End-to-end integration tests
- **tests/load_test.py**: Performance and concurrency tests
- **tests/conftest.py**: Shared pytest fixtures

## Dependencies

Managed with `uv` (pyproject.toml):
- `openai-agents>=0.6.1` - OpenAI Agents SDK
- `python-telegram-bot>=22.5` - Telegram bot framework
- `pypdf>=6.3.0` - PDF text extraction fallback
- `python-dotenv>=1.0.0` - Environment variable loading
- `pydantic-settings>=2.0.0` - Type-safe configuration
- `pytest>=8.0.0`, `pytest-asyncio>=0.23.0` - Testing

External system dependencies (installed in Docker):
- `ugrep` - Fast PDF text search
- `poppler-utils` - PDF text extraction (pdftotext)

## Important Notes

- **ALWAYS run bot as module**: `python -m src.main` (not `python src/main.py`)
- Root `main.py` is **deleted/deprecated** - use `src/main.py`
- Each user has isolated SQLite session database (prevents locks)
- All blocking operations wrapped in `asyncio.to_thread()` for async compatibility
- `ugrep` processes limited by semaphore to prevent resource exhaustion
- When you need info about OpenAI Agent SDK use Context& MCP to read doc