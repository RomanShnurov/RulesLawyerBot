# RulesLawyerBot

<p align="center">
  <img src="logo/RulesLawyerBot.png" alt="RulesLawyerBot Logo" width="400"/>
</p>

A production-ready Telegram bot that acts as a board game rules referee, using OpenAI's Agents SDK with a multi-stage conversational pipeline to search through PDF rulebooks and answer questions in multiple languages.

## Features

### Core Capabilities
- **Multi-Stage Conversational Pipeline**: Interactive game selection and clarification flow
- **Intelligent Rules Search**: Uses OpenAI Agents SDK to understand and answer rules questions
- **Schema-Guided Reasoning (SGR)**: Transparent reasoning chains with confidence scores
- **Streaming Progress Updates**: Fun, thematic progress messages during searches
- **Fast PDF Search**: Leverages `ugrep` and `pdftotext` for efficient text extraction
- **Multilingual Support**: Handles queries in English, Russian, and other languages
- **Smart Filename Translation**: Automatically translates localized game names to English filenames
- **Per-User Sessions**: Isolated SQLite conversation history for each user
- **Game Context Memory**: Remembers current game across conversation turns
- **Observability**: Optional Langfuse integration via OpenTelemetry for agent tracing and monitoring

### Interactive UI
- **Inline Keyboard Buttons**: Game selection via clickable buttons
- **Fuzzy Game Search**: `/games` command with smart search and suggestions
- **Context-Aware Responses**: Answers formatted with sources and related questions
- **Progress Indicators**: Real-time updates with creative status messages

### Production-Ready Features
- **Rate Limiting**: Configurable request limits per user (default: 10 req/min)
- **Concurrent Search Control**: Semaphore-based limits for resource management (max 4 concurrent searches)
- **Async Architecture**: Non-blocking operations for optimal performance
- **Long Message Handling**: Automatic splitting of responses >4000 characters
- **Graceful Shutdown**: Proper signal handling for zero-downtime deployments
- **Comprehensive Testing**: Unit tests, integration tests, and load testing

## Quick Start

### Using Docker (Recommended)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/RomanShnurov/RulesLawyerBot.git
   cd RulesLawyerBot
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual tokens
   ```

3. **Build and run:**
   ```bash
   just build  # or: make build
   just up     # or: make up
   ```

4. **View logs:**
   ```bash
   just logs   # or: make logs
   ```

See [docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md) for detailed Docker documentation.

### Local Development

1. **Install dependencies:**
   ```bash
   just install  # or: make install
   # or directly: uv sync
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your tokens
   ```

3. **Run the bot:**
   ```bash
   python -m src.main
   ```

## Environment Variables

### Required
- `TELEGRAM_TOKEN`: Your Telegram bot token (from @BotFather)
- `OPENAI_API_KEY`: Your OpenAI API key

### Optional
- `OPENAI_BASE_URL`: OpenAI API endpoint (default: `https://api.openai.com/v1`)
- `OPENAI_MODEL`: Model to use (default: `gpt-4o-mini`)
- `PDF_STORAGE_PATH`: PDF storage directory (default: `./rules_pdfs`)
- `DATA_PATH`: Data directory (default: `./data`)
- `LOG_LEVEL`: Logging level (default: `INFO`)
- `MAX_REQUESTS_PER_MINUTE`: Rate limiting (default: `10`)
- `MAX_CONCURRENT_SEARCHES`: Concurrent search limit (default: `4`)
- `ADMIN_USER_IDS`: Comma-separated list of admin Telegram user IDs
- `LANGFUSE_PUBLIC_KEY`: Langfuse public API key for observability (optional, leave empty to disable)
- `LANGFUSE_SECRET_KEY`: Langfuse secret API key for observability (optional)
- `LANGFUSE_BASE_URL`: Langfuse API endpoint (default: `https://cloud.langfuse.com`)
- `ENABLE_TRACING`: Enable OpenTelemetry tracing to Langfuse (default: `false`)
- `LANGFUSE_ENVIRONMENT`: Environment name for Langfuse traces (default: `production`)

## Bot Commands

### User Commands
- `/start` - Show welcome message and usage instructions
- `/games` - List all available games or search with `/games <query>`

### Examples
```
/games                    # List all games
/games wingspan          # Search for "Wingspan"
/games gloomy            # Fuzzy search finds "Gloomhaven"
```

## Development Commands

The project supports both `just` (recommended) and `make` command runners.

### Using just (recommended)
```bash
just             # Show available commands
just install     # Install dependencies with uv
just build       # Build Docker image
just up          # Start bot in Docker
just down        # Stop bot
just logs        # View logs
just restart     # Restart bot (down + up)
just test        # Run tests
just lint        # Run ruff linter
just format      # Format code with ruff
just clean       # Remove cache files
just setup       # Setup project from scratch
just validate    # Validate Docker setup
```

### Using make (alternative)
```bash
make help        # Show available commands
make install     # Install dependencies with uv
make build       # Build Docker image
make up          # Start bot in Docker
make down        # Stop bot
make logs        # View logs
make test        # Run tests
make lint        # Run ruff linter
make format      # Format code with ruff
make clean       # Remove cache files
```

## How It Works

### Multi-Stage Pipeline Flow

The bot uses a conversational pipeline that adapts based on user input:

1. **User sends a message** to the bot in any supported language
2. **Rate limiting** checks if user hasn't exceeded request limits
3. **Game Identification** - Determine which game to search:
   - Uses session context if game was discussed before
   - Shows inline keyboard buttons if multiple games match
   - Asks clarification if game name is unclear
4. **Agent processes the query** using OpenAI's Agents SDK with streaming:
   - `search_filenames(query)`: Find PDF files by game name
   - `search_inside_file_ugrep(filename, keywords)`: Fast regex search inside PDFs
   - `read_full_document(filename)`: Fallback PDF reader (pypdf)
   - Progress updates shown with fun thematic messages
5. **Clarification (if needed)** - Agent asks follow-up questions for complex queries
6. **Response generation** - Structured answer with:
   - Direct answer with quotes from rulebooks
   - Sources and page references
   - Confidence indicator (if < 80%)
   - Related questions suggestions
   - Full reasoning chain for admins
7. **Session persistence** - Conversation and game context saved to user's SQLite database

### Pipeline Action Types

- **CLARIFICATION_NEEDED**: Bot asks text question to clarify ambiguity
- **GAME_SELECTION**: Bot shows inline keyboard for game selection
- **SEARCH_IN_PROGRESS**: Bot reports search progress + asks question
- **FINAL_ANSWER**: Bot sends complete answer with reasoning

### Architecture Highlights

**Multi-Stage Pipeline**
- Conversational flow with game identification, clarification, search
- Inline keyboard buttons for interactive selection
- Context-aware responses using session history
- Structured outputs with `ActionType` discriminator

**Streaming & Progress**
- Real-time progress updates during agent execution
- Fun, thematic status messages (fantasy RPG theme)
- Debounced message updates to avoid spam
- Progress message deleted after final response

**Async-First Design**
- All blocking operations wrapped in `asyncio.to_thread()`
- Non-blocking Telegram event loop
- Concurrent request handling
- Streaming agent execution with event processing

**Per-User Isolation**
- Separate SQLite session database for each user
- Prevents database locks
- Conversation history maintained per user
- Per-user state tracking for UI flow (game context, pending questions)

**Schema-Guided Reasoning (SGR)**
- Structured outputs with complete reasoning chains
- Confidence scores and source references
- Transparent decision-making process
- Verbose mode for admins shows full reasoning

**Resource Management**
- Semaphore limits concurrent ugrep processes (default: 4)
- In-memory rate limiting per user (default: 10 req/min)
- Automatic output truncation to prevent token overflow

**Error Handling**
- User-friendly error messages
- Detailed logging for debugging
- Graceful degradation on tool failures

### Agent Tools

**`list_directory_tree()`**
- Lists all available PDF files with structure
- Used for game identification stage

**`search_filenames(query)`**
- Searches for PDF files in `rules_pdfs/` directory
- Case-insensitive filename matching
- Limits results to 50 files to prevent token overflow
- Returns `GameCandidate` objects with confidence scores

**`search_inside_file_ugrep(filename, keywords)`**
- Fast regex search using `ugrep` CLI
- PDF text extraction via `pdftotext` filter
- 2 lines of context around matches
- 30-second timeout protection
- Truncates output at 10,000 characters
- Semaphore-controlled for resource management

**`read_full_document(filename)`**
- Fallback PDF reader using `pypdf` library
- Extracts all pages with page markers
- Truncates at 100,000 characters
- Used when ugrep is unavailable or fails

### Special Features for Russian Language

**Morphology Handling**
- Uses regex patterns with word roots and synonyms
- Handles complex word endings automatically
- Example: For "movement", agent uses pattern `перемещ|движен|ход|бег`
- This matches: перемещение, переместить, движение, передвижение, ход, etc.

**Filename Translation**
- PDFs named using original English game titles
- Agent translates localized names before searching
- Example translations stored in agent instructions:
  - "Схватка в стиле фэнтези" → "Super Fantasy Brawl"
  - "Время приключений" → "Time of Adventure"
  - "Ужас Аркхэма" → "Arkham Horror"

## Technology Stack

### Core
- **Python 3.13**: Modern Python with latest features
- **OpenAI Agents SDK**: Agent framework with tool support
- **python-telegram-bot**: Async Telegram integration
- **uv**: Fast Python package manager

### PDF Processing
- **ugrep**: High-performance regex search (10x faster than grep)
- **poppler-utils**: PDF text extraction (`pdftotext`)
- **pypdf**: Pure Python PDF reader (fallback)

### Infrastructure
- **Docker**: Multi-stage containerization
- **SQLite**: Conversation persistence (per-user databases)
- **pydantic-settings**: Type-safe configuration

### Observability
- **Logfire**: Pydantic's observability platform with OpenTelemetry
- **Langfuse**: LLM application monitoring via OpenTelemetry OTLP

### Development
- **pytest**: Testing framework with async support
- **ruff**: Fast Python linter and formatter
- **mypy**: Static type checking
- **just/make**: Command runners for development tasks

## Adding PDF Rulebooks

Place PDF rulebooks in the `rules_pdfs/` directory. The bot will automatically search them.

**Naming Convention**: Use the original English game name for best results:
- ✅ `Wingspan.pdf`
- ✅ `Super Fantasy Brawl.pdf`
- ❌ `Крылья крылья.pdf` (Russian name - will work but harder to find)

## Testing

The project includes comprehensive testing:

### Run Tests
```bash
just test           # All tests with pytest
# or
pytest -v           # Verbose output
pytest tests/test_tools.py  # Specific test file
```

### Test Types
- **Unit Tests** (`tests/test_tools.py`): Test individual agent tools
- **Integration Tests** (`tests/test_integration.py`): End-to-end workflow testing
- **Load Tests** (`tests/load_test.py`): Performance and concurrency testing

### Test Fixtures
The `tests/conftest.py` provides shared fixtures:
- Temporary PDF files for testing
- Mock environment variables
- Isolated test directories

## Deployment

### Docker Deployment (Production)

1. **Set up environment:**
   ```bash
   cp .env.example .env
   # Edit .env with production tokens
   ```

2. **Build image:**
   ```bash
   just build
   ```

3. **Start bot:**
   ```bash
   just up
   ```

4. **Monitor logs:**
   ```bash
   just logs
   ```

See [docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md) for advanced deployment configurations.

## Documentation

**Complete documentation is available in the `docs/` directory:**

- **[docs/INDEX.md](docs/INDEX.md)** - Documentation overview and navigation
- **[docs/QUICKSTART.md](docs/QUICKSTART.md)** - Step-by-step getting started guide
- **[docs/DOCKER_SETUP.md](docs/DOCKER_SETUP.md)** - Docker deployment and troubleshooting
- **[docs/SGR_ARCHITECTURE.md](docs/SGR_ARCHITECTURE.md)** - Schema-Guided Reasoning implementation guide

## Troubleshooting

### Bot doesn't start
- Check `.env` file exists with valid `TELEGRAM_TOKEN` and `OPENAI_API_KEY`
- Verify Docker is running: `docker ps`
- Check logs: `just logs`

### ugrep not found
- Install ugrep: `apt-get install ugrep` (Linux) or `brew install ugrep` (macOS)
- Or use Docker deployment (ugrep pre-installed)

### Database locked errors
- Ensure each user has isolated session DB (implemented in current version)
- Check `data/sessions/` directory permissions

### Rate limit errors
- Adjust `MAX_REQUESTS_PER_MINUTE` in `.env`
- Increase for trusted users or decrease for public bots

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues and questions, please open an issue on GitHub.

---

Made with ♥ for board game enthusiasts
