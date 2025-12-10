# Documentation Index

> **START HERE**: This is the primary documentation index for RulesLawyerBot. AI assistants and developers should begin here to understand the project structure and locate relevant documentation.

## Project Overview

**RulesLawyerBot** is a Telegram bot that acts as a board game rules referee, using OpenAI's Agents SDK to intelligently search through PDF rulebooks and answer questions in multiple languages (English, Russian, etc.).

**Key Technologies**: OpenAI Agents SDK | python-telegram-bot | ugrep | Docker | SQLite | Python 3.11+

---

## Quick Navigation

### Getting Started
- [**README.md**](../README.md) - Main project documentation, features, and setup
- [**QUICKSTART.md**](QUICKSTART.md) - Get the bot running in 5 minutes
- [**DOCKER_SETUP.md**](DOCKER_SETUP.md) - Detailed Docker configuration and deployment guide

### Implementation Plans

#### MVP Development Plans
- [**mvp/COMPREHENSIVE_IMPLEMENTATION_PLAN.md**](plans/mvp/COMPREHENSIVE_IMPLEMENTATION_PLAN.md) - Complete refactoring roadmap (7-10 days)
- [**mvp/overview.md**](plans/mvp/overview.md) - Architecture overview and design principles
- [**mvp/phases/phase1.md**](plans/mvp/phases/phase1.md) - Phase 1: Infrastructure & Docker
- [**mvp/phases/phase2.md**](plans/mvp/phases/phase2.md) - Phase 2: Core Refactoring
- [**mvp/phases/phase3.md**](plans/mvp/phases/phase3.md) - Phase 3: Safety & Reliability
- [**mvp/phases/phase4.md**](plans/mvp/phases/phase4.md) - Phase 4: Telegram Integration
- [**mvp/phases/phase5.md**](plans/mvp/phases/phase5.md) - Phase 5: Testing & Deployment

#### Planning Documents
- [**plans/next_steps.md**](plans/next_steps.md) - External planning resources and references

### Architecture & Analysis
- [**SGR_ARCHITECTURE.md**](SGR_ARCHITECTURE.md) - **Schema-Guided Reasoning implementation guide** (transparent agent reasoning)
- [**other/architecture_review_and_recommendations.md**](other/architecture_review_and_recommendations.md) - Architecture analysis and improvement recommendations
- [**other/plan_review.md**](other/plan_review.md) - Review of implementation plans
- [**other/implementation_plan_with_existed_code.md**](other/implementation_plan_with_existed_code.md) - Implementation strategy based on existing codebase

### Code Reference
- [**../CLAUDE.md**](../CLAUDE.md) - Instructions for Claude Code agent (architecture, patterns, conventions)

---

## Project Structure

```
RulesLawyerBot/
├── src/
│   ├── __init__.py
│   └── main.py              # Main bot application (single-file currently)
├── rules_pdfs/              # PDF rulebook storage directory
├── data/
│   ├── sessions/            # SQLite session databases (per-user)
│   └── app.log              # Application logs
├── docs/                    # This documentation directory
│   ├── INDEX.md             # This file
│   ├── QUICKSTART.md
│   ├── DOCKER_SETUP.md
│   ├── plans/               # Development plans
│   └── other/               # Architecture docs and analysis
├── Dockerfile               # Multi-stage Docker build
├── docker-compose.yml       # Docker Compose configuration
├── pyproject.toml           # Python dependencies (uv)
├── uv.lock                  # Locked dependencies
├── Makefile                 # Development commands
├── justfile                 # Alternative command runner (just)
└── README.md                # Main project documentation
```

---

## Key Features

- **Schema-Guided Reasoning (SGR)**: Transparent, auditable agent reasoning with structured Pydantic outputs
- **Intelligent Rules Search**: Uses OpenAI Agents SDK to understand and answer complex rules questions
- **Fast PDF Search**: Leverages `ugrep` with `pdftotext` for efficient text extraction and search
- **Multilingual Support**: Handles queries in English, Russian, and other languages
- **Smart Filename Translation**: Automatically translates localized game names to English filenames
- **Persistent Conversations**: Maintains conversation history with SQLite sessions
- **Morphology-Aware Search**: Special regex patterns for Russian language word roots and synonyms
- **Debug Mode**: Users can enable `/debug` to see the full reasoning chain

---

## Development Workflow

### Quick Commands
```bash
# Using just (recommended)
just install    # Install dependencies
just build      # Build Docker image
just up         # Start bot
just logs       # View logs
just down       # Stop bot

# Using make (alternative)
make install    # Install dependencies
make build      # Build Docker image
make up         # Start bot
make logs       # View logs
make down       # Stop bot
```

### Environment Variables
See [.env.example](../.env.example) for required configuration:
- `TELEGRAM_TOKEN` - Required: Your Telegram bot token
- `OPENAI_API_KEY` - Required: Your OpenAI API key
- `OPENAI_BASE_URL` - Optional: Custom API endpoint
- `OPENAI_MODEL` - Optional: Model selection (default: gpt-5-nano)

---

## Current Implementation Status

**Current State**: Single-file prototype (`src/main.py`)
- [x] Working Telegram bot with OpenAI Agents SDK integration
- [x] PDF search via ugrep and pypdf fallback
- [x] Multilingual support (EN/RU)
- [x] Docker containerization
- [x] Basic logging and session management

**Planned Improvements** (see MVP plans):
- [ ] Modular architecture refactoring
- [ ] Per-user session isolation
- [ ] Rate limiting and resource management
- [ ] Comprehensive testing suite
- [ ] Production monitoring and health checks

---

## For AI Assistants (Claude Code)

When working with this codebase:

1. **Start with CLAUDE.md** - Contains critical instructions, architecture patterns, and conventions
2. **Check current implementation** - The bot is currently a single-file app in `src/main.py`
3. **Reference MVP plans** - Before making changes, review the comprehensive implementation plan
4. **Use existing patterns** - Follow the agent tools pattern (`@function_tool` decorator)
5. **Test with Docker** - Always verify changes work in the containerized environment

### Important Codebase Patterns

- **Agent Tools**: Defined with `@function_tool` decorator, must have docstrings and type hints
- **Logging**: Dual logging to console and `app.log` with UTF-8 encoding
- **Session Management**: Uses `SQLiteSession` with conversation ID `"conversation_roman"`
- **PDF Search**: Prefer `ugrep` for speed, fallback to `pypdf` if unavailable
- **Russian Language**: Use regex patterns with word roots (e.g., `перемещ|движен|ход|бег` for "movement")

---

## Support and Contributing

- **Issues**: Report bugs and feature requests on GitHub
- **Development**: Follow the phased implementation plan in `docs/plans/mvp/`
- **Testing**: Run `just test` or `make test` before submitting changes
- **Code Style**: Use `just lint` and `just format` (ruff)

---

**Last Updated**: 2025-12-06
**Documentation Maintainer**: Project team
