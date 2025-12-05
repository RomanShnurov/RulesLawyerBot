**Project:** RulesLawyerBot
**Goal:** Refactor single-file prototype into production-ready containerized application
**Tech Stack:** OpenAI Agents SDK + python-telegram-bot + ugrep + Docker


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
