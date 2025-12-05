# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RulesLawyerBot is a Telegram bot that acts as a board game rules referee, using OpenAI's Agents SDK to search through PDF rulebooks and answer questions. The bot supports multilingual queries (English, Russian, etc.) and uses both filename search and fast text search (via `ugrep`) to find relevant rules.

## Quick Commands

### Using just (recommended)
```bash
just                 # Show all commands
just install         # Install dependencies with uv
just build           # Build Docker image
just up              # Start bot in Docker (detached)
just down            # Stop bot
just logs            # View live logs
just restart         # Restart bot (down + up)
just test            # Run tests
just lint            # Run ruff linter
just format          # Format code
just setup           # Setup from scratch (creates .env, directories, installs deps)
```

### Using make (alternative)
```bash
make help            # Show all commands
make install         # Install dependencies
make build           # Build Docker image
make up              # Start bot in Docker
make down            # Stop bot
make logs            # View live logs
```

### Running Locally (without Docker)
```bash
python -m src.main
```

## Documentation System

**START HERE**: [docs/INDEX.md](docs/INDEX.md) - Complete documentation map with links to all guides.

When answering questions, prefer linking to existing documentation rather than repeating information:
- Getting started → [docs/QUICKSTART.md](docs/QUICKSTART.md)
- Docker setup → [docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md)
- Architecture → [docs/plans/mvp/overview.md](docs/plans/mvp/overview.md)
- Implementation phases → [docs/plans/mvp/COMPREHENSIVE_IMPLEMENTATION_PLAN.md](docs/plans/mvp/COMPREHENSIVE_IMPLEMENTATION_PLAN.md)
- Next steps → [docs/plans/next_steps.md](docs/plans/next_steps.md)

## Core Architecture

### Single-Module Application (src/main.py)

The entire bot is a **single Python file** with these components:

**1. OpenAI Agents SDK Integration**
- Uses `agents.Agent` with `OpenAIChatCompletionsModel` and `SQLiteSession`
- Agent name: "Board Game Referee"
- Session database: `./data/sessions/conversation.db`
- Tracing disabled for performance

**2. Agent Tools (defined with `@function_tool` decorator)**
- `search_filenames(query)`: Searches for PDF files in `./rules_pdfs/` directory
- `search_inside_file_ugrep(filename, keywords)`: Uses `ugrep` CLI with XML filter to search PDF contents
- `read_full_document(filename)`: Fallback PDF reader using `pypdf` (limited to 100k chars)

**3. Telegram Bot (python-telegram-bot)**
- Async handlers: `start_command`, `handle_message`
- Sends typing action while processing
- Truncates responses to 3500 chars (Telegram limit)

**4. Performance Monitoring**
- `ScopeTimer` context manager logs execution time for each tool call

### Critical Configuration

All configuration via environment variables (loaded from `.env`):
- `TELEGRAM_TOKEN`: Bot token from @BotFather **(REQUIRED)**
- `OPENAI_API_KEY`: OpenAI API key **(REQUIRED)**
- `OPENAI_BASE_URL`: API endpoint (default: `https://api.proxyapi.ru/openai/v1`)
- `OPENAI_MODEL`: Model name (default: `gpt-5-nano`)
- `PDF_STORAGE_PATH`: PDF directory (default: `./rules_pdfs`)
- `DATA_PATH`: Data directory for logs/sessions (default: `./data`)
- `LOG_LEVEL`: Logging level (default: `INFO`)

### Agent Instructions Pattern

The agent has **specialized multilingual search logic**:

1. **Localized Game Name Translation**: PDFs are named using **original English titles**. When users provide localized names (e.g., Russian "Схватка в стиле фэнтези"), the agent translates to English ("Super Fantasy Brawl") before searching.

2. **Russian Morphology Handling**: Due to complex Russian word endings, the agent uses **regex patterns with word roots and synonyms** instead of exact words:
   - Example: Instead of "перемещение", uses `перемещ|движен|ход|бег` for "movement"

This logic is encoded in agent instructions (src/main.py:197-227).

### Docker Multi-Stage Build

**CRITICAL**: Python version **must match** between Dockerfile and pyproject.toml:
- Current requirement: **Python 3.13** (pyproject.toml:6)
- Dockerfile uses: **python:3.13-slim** (lines 4, 20)

Build stages:
1. **Builder stage**: Installs dependencies with `uv sync --frozen --no-dev`
2. **Runtime stage**: Copies virtualenv, installs system deps (ugrep, poppler-utils), runs as non-root user

## Key Implementation Details

### Logging
- Dual output: console (stdout) + file (`./data/app.log`)
- Configurable via `LOG_LEVEL` environment variable
- UTF-8 encoding (important for Russian text)
- Reduced noise: `httpcore` and `telegram` loggers set to INFO level

### Agent Execution Flow
1. User sends message to Telegram
2. Bot sends "typing" action
3. `Runner.run()` executes agent with message and session
4. Agent calls tools based on instructions
5. Final output truncated to 3500 chars and sent to user
6. Steps and tool calls logged for debugging

### PDF Search Strategy
1. **Filename search first**: Find matching PDFs using game name
2. **Fast content search**: Use `search_inside_file_ugrep` with regex patterns
3. **Fallback**: Use `read_full_document` if ugrep fails or unavailable
4. **Truncation limits**: ugrep output (10k chars), full document (100k chars)

### Session Management
- Uses `SQLiteSession` for conversation persistence
- Database path: `{DATA_PATH}/sessions/conversation.db`
- Single session for all users (current implementation)

## Common Modification Scenarios

### Adding New Agent Tools
1. Define function with type hints and docstring
2. Decorate with `@function_tool`
3. Add to `rules_agent.tools` list (src/main.py:225)

### Changing API Configuration
- Modify environment variables in `.env` file
- Update defaults in `src/main.py` if needed

### Supporting Additional Languages
Update agent instructions (src/main.py:197-227) with:
- Language-specific search patterns
- Translation guidelines for filename searches
- Morphology handling rules

### Customizing Response/Search Limits
- Telegram message: src/main.py:251 (`result.final_output[:3500]`)
- ugrep output: src/main.py:155 (10,000 chars)
- Full document: src/main.py:189 (100,000 chars)

## Dependencies

Managed with `uv` (defined in `pyproject.toml`):
- `openai-agents>=0.6.1` - OpenAI Agents SDK
- `python-telegram-bot>=22.5` - Telegram bot framework
- `pypdf>=6.3.0` - PDF text extraction fallback
- `python-dotenv>=1.0.0` - Environment variable loading

External system dependencies (installed in Docker):
- `ugrep` - Fast PDF text search
- `poppler-utils` - PDF text extraction (pdftotext)

## Notes

- Root `main.py` is **deprecated** - use `src/main.py` instead
- Run bot via: `python -m src.main` (not `python src/main.py`)
- The codebase is intentionally simple: single file, minimal abstraction
- Session handling is currently single-user (hardcoded session ID in old version, now per-database file)
