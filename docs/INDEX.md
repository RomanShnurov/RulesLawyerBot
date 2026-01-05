# Documentation Index

> **START HERE**: This is the primary documentation index for RulesLawyerBot. AI assistants and developers should begin here to understand the project structure and locate relevant documentation.

## Project Overview

**RulesLawyerBot** is a production-ready Telegram bot that acts as a board game rules referee, using OpenAI's Agents SDK with a multi-stage conversational pipeline to search through PDF rulebooks and answer questions in multiple languages.

**Key Technologies**: OpenAI Agents SDK | python-telegram-bot | ugrep | Docker | SQLite | Python 3.13+

**Status**: ✅ **Production Ready** - All MVP features implemented and tested

---

## Quick Navigation

### Getting Started
- [**README.md**](../README.md) - Main project documentation, features, and setup
- [**QUICKSTART.md**](QUICKSTART.md) - Get the bot running in 5 minutes
- [**DOCKER_SETUP.md**](DOCKER_SETUP.md) - Detailed Docker configuration and deployment guide

### Configuration & Setup
- [**GAMES_INDEX.md**](GAMES_INDEX.md) - Multilingual games index setup and usage
- [**BGG_API_SETUP.md**](BGG_API_SETUP.md) - BoardGameGeek API setup for automatic game metadata

### Architecture & Technical Guides
- [**SGR_ARCHITECTURE.md**](SGR_ARCHITECTURE.md) - **Schema-Guided Reasoning implementation guide** (transparent agent reasoning with structured outputs)
- [**../CLAUDE.md**](../CLAUDE.md) - Instructions for Claude Code agent (architecture, patterns, conventions)

---

## Project Structure

```
RulesLawyerBot/
├── src/                     # Source code (modular architecture)
│   ├── __init__.py
│   ├── main.py              # Telegram bot entry point (async handlers)
│   ├── config.py            # Settings with pydantic-settings
│   ├── agent/               # OpenAI Agent configuration
│   │   ├── definition.py    # Agent creation & session management
│   │   ├── tools.py         # Agent tools (@function_tool decorated)
│   │   └── schemas.py       # Pydantic schemas for SGR pipeline
│   ├── handlers/            # Telegram event handlers
│   │   ├── commands.py      # Command handlers (/start, /games)
│   │   ├── messages.py      # Message handler with streaming
│   │   └── callbacks.py     # Inline button callback handlers
│   ├── pipeline/            # Multi-stage pipeline logic
│   │   ├── handler.py       # Pipeline output routing
│   │   └── state.py         # Conversation state management
│   ├── formatters/          # Output formatting
│   │   └── __init__.py      # (Empty - formatting done inline)
│   └── utils/               # Utility modules
│       ├── logger.py        # Logging configuration
│       ├── timer.py         # Performance monitoring (ScopeTimer)
│       ├── safety.py        # Rate limiting, semaphore, error handling
│       ├── telegram_helpers.py  # Message splitting utilities
│       ├── conversation_state.py # Per-user state tracking
│       ├── progress_reporter.py  # Streaming progress updates
│       └── observability.py # Langfuse integration via OpenTelemetry
├── tests/                   # Comprehensive test suite
│   ├── conftest.py          # Pytest fixtures
│   ├── test_tools.py        # Unit tests for agent tools
│   ├── test_integration.py  # End-to-end integration tests
│   └── load_test.py         # Performance/load testing
├── rules_pdfs/              # PDF rulebook storage directory
├── data/
│   ├── sessions/            # SQLite session databases (per-user isolation)
│   └── app.log              # Application logs
├── docs/                    # Documentation
│   ├── INDEX.md             # This file - documentation entry point
│   ├── QUICKSTART.md        # Quick start guide
│   ├── DOCKER_SETUP.md      # Docker deployment guide
│   ├── SGR_ARCHITECTURE.md  # Schema-Guided Reasoning technical guide
│   ├── GAMES_INDEX.md       # Games index documentation
│   └── BGG_API_SETUP.md     # BoardGameGeek API setup guide
├── scripts/                 # Utility scripts
│   └── generate_games_index.py  # Auto-generate games index from PDFs
├── Dockerfile               # Multi-stage Docker build (Python 3.13)
├── docker-compose.yml       # Docker Compose configuration
├── .env.example             # Example environment variables
├── .dockerignore            # Docker build exclusions
├── pyproject.toml           # Python dependencies (uv)
├── uv.lock                  # Locked dependencies
├── Makefile                 # Development commands (make)
├── justfile                 # Development commands (just - recommended)
├── CLAUDE.md                # Claude Code instructions
└── README.md                # Main project documentation
```

---

## Key Features

### Core Capabilities
- **Multi-Stage Conversational Pipeline**: Interactive game selection, clarification, search, and answer flow
- **Schema-Guided Reasoning (SGR)**: Transparent agent reasoning with structured Pydantic outputs and confidence scores
- **Intelligent Rules Search**: OpenAI Agents SDK with specialized tools for PDF search
- **Streaming Progress Updates**: Real-time progress messages with fun thematic updates during agent execution
- **Fast PDF Search**: Leverages `ugrep` and `pdftotext` for 10x faster search than standard grep
- **Multilingual Support**: Handles queries in English, Russian, and other languages

### Interactive UI
- **Inline Keyboard Buttons**: Interactive game selection with clickable buttons
- **Fuzzy Game Search**: `/games` command with smart search and suggestions
- **Context-Aware Responses**: Remembers current game across conversation turns
- **Long Message Handling**: Automatic splitting of responses >4000 characters

### Production Features
- **Per-User Session Isolation**: Separate SQLite database per user (prevents database locks)
- **Rate Limiting**: Configurable per-user request limits (default: 10 req/min)
- **Concurrent Search Control**: Semaphore-based resource management (max 4 concurrent searches)
- **Async Architecture**: Non-blocking operations with asyncio.to_thread() wrapping
- **Graceful Shutdown**: Proper signal handling for zero-downtime deployments
- **Comprehensive Testing**: Unit tests, integration tests, and load testing

### Advanced Features
- **Smart Filename Translation**: Automatically translates localized game names to English filenames
- **Morphology-Aware Search**: Special regex patterns for Russian language word roots and synonyms
- **Confidence Indicators**: Visual indicators (✅/⚠️/❓) showing agent's confidence level
- **Source References**: All answers include page numbers and file references
- **Related Questions**: Agent suggests follow-up questions after each answer
- **Observability**: Optional Langfuse integration via OpenTelemetry for agent tracing and monitoring

---

## Development Workflow

### Quick Commands

**Using just (recommended):**
```bash
just             # Show all available commands
just install     # Install dependencies with uv
just run-local   # Run bot locally without Docker
just test        # Run tests with pytest
just lint        # Run ruff linter
just format      # Format code with ruff
just build       # Build Docker image
just up          # Start bot in Docker (detached)
just down        # Stop bot
just logs        # View live logs
just restart     # Restart bot (down + up)
just setup       # Setup from scratch (creates .env, directories, installs deps)
just validate    # Validate Docker setup
just clean       # Remove cache files
```

**Using make (alternative):**
```bash
make help        # Show available commands
make install     # Install dependencies with uv
make test        # Run tests
make lint        # Run ruff linter
make format      # Format code with ruff
make build       # Build Docker image
make up          # Start bot in Docker
make down        # Stop bot
make logs        # View logs
make clean       # Remove cache files
```

### Environment Variables

See [.env.example](../.env.example) for configuration options:

**Required:**
- `TELEGRAM_TOKEN` - Your Telegram bot token (from @BotFather)
- `OPENAI_API_KEY` - Your OpenAI API key

**Optional:**
- `OPENAI_BASE_URL` - Custom API endpoint (default: `https://api.openai.com/v1`)
- `OPENAI_MODEL` - Model to use (default: `gpt-4o-mini`, recommended for reliable tool calling)
- `PDF_STORAGE_PATH` - PDF storage directory (default: `./rules_pdfs`)
- `DATA_PATH` - Data directory (default: `./data`)
- `LOG_LEVEL` - Logging level (default: `INFO`)
- `MAX_REQUESTS_PER_MINUTE` - Rate limiting (default: `10`)
- `MAX_CONCURRENT_SEARCHES` - Concurrent search limit (default: `4`)
- `ADMIN_USER_IDS` - Comma-separated admin Telegram user IDs
- `LANGFUSE_PUBLIC_KEY` - Langfuse public API key for observability (optional)
- `LANGFUSE_SECRET_KEY` - Langfuse secret API key for observability (optional)
- `LANGFUSE_BASE_URL` - Langfuse API endpoint (default: `https://cloud.langfuse.com`)
- `ENABLE_TRACING` - Enable OpenTelemetry tracing to Langfuse (default: `false`)
- `LANGFUSE_ENVIRONMENT` - Environment name for Langfuse traces (default: `production`)
- `BGG_API_TOKEN` - BoardGameGeek API token for auto-generating game metadata (optional, see [BGG_API_SETUP.md](BGG_API_SETUP.md))

---

## Implementation Status

**Current Version**: v0.2.0 - Production Ready

### ✅ Completed Features

**Core Architecture:**
- ✅ Modular architecture with separate modules (agent, handlers, pipeline, formatters, utils)
- ✅ Per-user session isolation (separate SQLite databases)
- ✅ Rate limiting and resource management (configurable limits)
- ✅ Async architecture for optimal performance
- ✅ Comprehensive testing suite (unit, integration, load tests)
- ✅ Docker multi-stage build (Python 3.13)

**Multi-Stage Pipeline:**
- ✅ Interactive conversational pipeline with game identification
- ✅ Inline keyboard buttons for game selection
- ✅ Clarification flow for ambiguous queries
- ✅ Streaming progress updates with fun thematic messages
- ✅ Game context persistence across conversation
- ✅ Callback query handlers for UI interactions

**Schema-Guided Reasoning (SGR):**
- ✅ Structured Pydantic outputs with complete reasoning chains
- ✅ Confidence scores and source references
- ✅ Query analysis and search planning
- ✅ Follow-up search tracking
- ✅ Transparent decision-making process

**User Features:**
- ✅ `/start` command with welcome message
- ✅ `/games` command with fuzzy search
- ✅ Multilingual support (English, Russian)
- ✅ Smart filename translation
- ✅ Morphology-aware search for Russian
- ✅ Long message handling (auto-split >4000 chars)
- ✅ Progress indicators and confidence visualization


---

## For AI Assistants (Claude Code)

When working with this codebase:

1. **Start with [CLAUDE.md](../CLAUDE.md)** - Contains critical instructions, architecture patterns, and conventions
2. **Understand modular structure** - Code organized into agent/, handlers/, pipeline/, formatters/, utils/
3. **Follow existing patterns** - Use `@function_tool` for agent tools, async handlers for Telegram
4. **Test thoroughly** - Run `just test` before committing changes
5. **Verify in Docker** - Always test changes work in containerized environment

### Important Codebase Patterns

**Agent System:**
- **Agent Tools**: Defined with `@function_tool` decorator in [src/agent/tools.py](../src/agent/tools.py)
- **Schemas**: Pydantic models in [src/agent/schemas.py](../src/agent/schemas.py) for structured outputs
- **Session Management**: Per-user SQLite databases in `data/sessions/user_{user_id}.db`

**Telegram Handlers:**
- **Commands**: Async handlers in [src/handlers/commands.py](../src/handlers/commands.py)
- **Messages**: Streaming handler in [src/handlers/messages.py](../src/handlers/messages.py)
- **Callbacks**: Inline button handlers in [src/handlers/callbacks.py](../src/handlers/callbacks.py)

**Pipeline:**
- **Output Routing**: [src/pipeline/handler.py](../src/pipeline/handler.py) routes `PipelineOutput` by `ActionType`
- **State Management**: [src/pipeline/state.py](../src/pipeline/state.py) tracks game context per user

**Utilities:**
- **Logging**: Dual output (console + file) with UTF-8 encoding in [src/utils/logger.py](../src/utils/logger.py)
- **Safety**: Rate limiting and semaphores in [src/utils/safety.py](../src/utils/safety.py)
- **Progress**: Streaming updates in [src/utils/progress_reporter.py](../src/utils/progress_reporter.py)

**Language Support:**
- **Russian Morphology**: Use regex patterns with word roots (e.g., `перемещ|движен|ход|бег` for "movement")
- **Filename Translation**: Agent translates localized names to English before search

---

## Testing

Run tests with: `just test` or `pytest -v`

**Test Structure:**
- **[tests/test_tools.py](../tests/test_tools.py)**: Unit tests for agent tools
- **[tests/test_integration.py](../tests/test_integration.py)**: End-to-end integration tests
- **[tests/load_test.py](../tests/load_test.py)**: Performance and concurrency tests
- **[tests/conftest.py](../tests/conftest.py)**: Shared pytest fixtures

**Coverage:**
- Agent tool functionality (search, file reading)
- Rate limiting and semaphore controls
- Multi-stage pipeline flow
- Concurrent request handling
- Error handling and edge cases

---

## Support and Contributing

**Development Workflow:**
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes following existing patterns
4. Run tests: `just test` (or `make test`)
5. Run linting: `just lint` and format: `just format`
6. Commit changes: `git commit -m "Description"`
7. Push to branch: `git push origin feature/your-feature`
8. Submit a pull request

**Code Style:**
- Follow PEP 8 style guide
- Use type hints for all functions
- Write docstrings for public APIs
- Keep line length ≤100 characters
- Run `ruff` before committing

**Issues:**
- Report bugs and feature requests on GitHub
- Include logs and reproduction steps
- Check existing issues before creating new ones

---

**Last Updated**: 2025-12-16
**Documentation Maintainer**: Project team
