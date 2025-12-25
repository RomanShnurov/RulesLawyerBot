# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RulesLawyerBot is a production-ready Telegram bot that acts as a board game rules referee, using OpenAI's Agents SDK with a multi-stage conversational pipeline to search through PDF rulebooks and answer questions in multiple languages.

**Key Features**: Multi-stage pipeline with inline UI, Schema-Guided Reasoning (SGR), streaming progress updates, async architecture, per-user session isolation, rate limiting, concurrent search control, comprehensive testing.

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
- [docs/SGR_ARCHITECTURE.md](docs/plans/mvp/overview.md) - SGR overview

## Architecture

### Modular Structure

```
src/
├── main.py                 # Telegram bot entry point (async handlers)
├── config.py               # Settings with pydantic-settings
├── agent/
│   ├── definition.py       # Agent creation & session management
│   ├── tools.py            # Agent tools (@function_tool decorated)
│   └── schemas.py          # Pydantic schemas for SGR pipeline
├── handlers/
│   ├── commands.py         # Command handlers (/start, /games)
│   ├── messages.py         # Message handler with streaming
│   └── callbacks.py        # Inline button callback handlers
├── pipeline/
│   ├── handler.py          # Multi-stage pipeline output routing
│   └── state.py            # Conversation state management
├── formatters/
│   └── sgr.py              # Schema-Guided Reasoning output formatting
└── utils/
    ├── logger.py           # Logging configuration
    ├── timer.py            # Performance monitoring (ScopeTimer)
    ├── safety.py           # Rate limiting, semaphore, error handling
    ├── telegram_helpers.py # Message splitting utilities
    ├── conversation_state.py # Per-user state tracking
    └── progress_reporter.py  # Streaming progress updates
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
- **schemas.py**: Pydantic models for structured outputs
  - `PipelineOutput`: Multi-stage pipeline with `ActionType` discriminator
  - `FinalAnswer`: Simplified final answer with formatted text and metadata
  - `GameIdentification`, `SearchProgress`: Pipeline stage schemas

**3. Multi-Stage Pipeline (src/pipeline/)**
- **handler.py**: Routes pipeline outputs to Telegram UI
  - `handle_pipeline_output()`: Processes agent output by `ActionType`
  - `build_game_selection_keyboard()`: Creates inline button menus
- **state.py**: Per-user conversation state management
  - `get_conversation_state()`: Retrieves state from `context.user_data`
  - Tracks current game context, pending clarifications

**4. Telegram Handlers (src/handlers/)**
- **commands.py**: Command implementations
  - `start_command()`: Welcome message with usage instructions
  - `games_command()`: List/search available games with fuzzy matching
- **messages.py**: Main message processing
  - `handle_message()`: Multi-stage pipeline with streaming progress
  - Context injection for game-aware conversations
- **callbacks.py**: Inline button handlers
  - `handle_game_selection()`: Process game selection from inline keyboard

**5. Utilities (src/utils/)**
- **logger.py**: Dual output (console + file), UTF-8 encoding
- **timer.py**: `ScopeTimer` context manager for performance monitoring
- **safety.py**: `rate_limiter` (per-user), `ugrep_semaphore` (concurrent search control)
- **telegram_helpers.py**: `send_long_message()` splits long responses
- **conversation_state.py**: Per-user state tracking (game context, UI stage)
- **progress_reporter.py**: Streaming progress updates with fun messages

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

### Multi-Stage Pipeline Architecture

The bot uses a **conversational pipeline** with multiple stages (src/agent/schemas.py):

**Pipeline Flow**:
1. **Game Identification**: Determine which game the user is asking about
   - Uses session context or asks for clarification
   - Shows inline keyboard for game selection if ambiguous
2. **Clarification**: Ask follow-up questions if query is unclear
3. **Search**: Execute searches with progress updates
4. **Final Answer**: Return complete answer with reasoning chain

**Action Types** (`ActionType` enum):
- `CLARIFICATION_NEEDED`: Bot asks text question
- `GAME_SELECTION`: Bot shows inline keyboard buttons
- `SEARCH_IN_PROGRESS`: Bot reports search progress + asks question
- `FINAL_ANSWER`: Bot sends complete answer

**Conversation State** (src/utils/conversation_state.py):
- Per-user state stored in `context.user_data`
- Tracks: current game, pending questions, UI stage
- Game context persists across questions in same session

### Agent Instructions Pattern

The agent has **specialized multilingual search logic** (src/agent/definition.py):

1. **Localized Game Name Translation**: PDFs named using **original English titles**
   - User says "Схватка в стиле фэнтези" → Agent translates to "Super Fantasy Brawl"

2. **Russian Morphology Handling**: Uses **regex patterns with word roots and synonyms**
   - Example: "movement" → `перемещ|движен|ход|бег`
   - Example: "attack" → `атак|удар|бой|сраж`

3. **Structured Pipeline Outputs**:
   - Agent outputs structured `PipelineOutput` with multi-stage routing
   - Final answers include confidence scores and metadata
   - Transparent decision-making via `ActionType` discriminator

4. **Mandatory Tool Calling Workflow**:
   - Agent MUST call tools before outputting structured response
   - Sequence: `list_directory_tree()` → `search_filenames()` → `search_inside_file_ugrep()`
   - Instructions explicitly forbid predicting/guessing tool results

**IMPORTANT**: The structured output pattern requires a capable model. Small/fast models (like `gpt-3.5-turbo` or lightweight alternatives) may skip tool calls and predict results. **Recommended models**: `gpt-4o`, `gpt-4-turbo`, or `gpt-4` for reliable tool calling behavior.

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
1. Define async handler in `src/handlers/commands.py`
2. Import in `src/main.py` and register with `application.add_handler(CommandHandler("command_name", handler))`

### Adding Inline Button Handlers
1. Define async handler in `src/handlers/callbacks.py`
2. Register in `src/main.py` with `CallbackQueryHandler(handler, pattern="^prefix:")`
3. Use callback data format: `"action:parameter"` for parsing

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