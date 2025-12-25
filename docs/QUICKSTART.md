# Quick Start Guide

Get RulesLawyerBot running in 5 minutes with Docker, or run locally for development.

## Prerequisites

**For Docker (Recommended):**
- Docker and Docker Compose installed
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- OpenAI API key

**For Local Development:**
- Python 3.13+ installed
- [uv](https://github.com/astral-sh/uv) package manager (optional but recommended)
- `ugrep` and `poppler-utils` installed on your system
- Telegram bot token and OpenAI API key

---

## Option 1: Docker Setup (Recommended)

### Step 1: Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit with your tokens
# Windows: notepad .env
# Mac/Linux: nano .env
```

**Required values to change:**
```env
TELEGRAM_TOKEN=YOUR_TELEGRAM_TOKEN_HERE
OPENAI_API_KEY=YOUR_OPENAI_KEY_HERE
```

**Recommended optional settings:**
```env
# The default model is gpt-4o-mini (provides reliable tool calling)
# You can optionally upgrade to gpt-4o for best performance
OPENAI_MODEL=gpt-4o  # Optional: use gpt-4o for maximum performance
```

### Step 2: Build and Start

**Using just (recommended):**
```bash
just build  # Build the Docker image
just up     # Start the bot in background
```

**Using make (alternative):**
```bash
make build  # Build the Docker image
make up     # Start the bot in background
```

That's it! The bot is now running in a Docker container.

### Step 3: Verify

```bash
# View logs to confirm it started
just logs   # or: make logs
```

You should see output like:
```
Starting Board Game Rules Bot
OpenAI Model: gpt-4o-mini
PDF Storage: /app/rules_pdfs
Bot started. Press Ctrl+C to stop.
```

### Step 4: Test the Bot

1. Open Telegram
2. Find your bot by username
3. Send `/start` to see the welcome message
4. Try commands:
   - `/games` - List all available games
   - `/games wingspan` - Search for a specific game

If you have PDF rulebooks in `rules_pdfs/`, you can ask questions like:
- "How do I play Wingspan?"
- "What are the attack rules in Gloomhaven?"

---

## Option 2: Local Development Setup

### Step 1: Install Dependencies

**Using uv (recommended):**
```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh  # Mac/Linux
# or: pip install uv

# Install dependencies
just install  # or: uv sync
```

**Using pip:**
```bash
pip install -r requirements.txt  # Not recommended - uv is faster
```

### Step 2: Install System Dependencies

**macOS:**
```bash
brew install ugrep poppler
```

**Ubuntu/Debian:**
```bash
sudo apt-get install ugrep poppler-utils
```

**Windows:**
- Download ugrep from https://github.com/Genivia/ugrep/releases
- Download Poppler from https://github.com/oschwartz10612/poppler-windows/releases
- Add both to PATH

### Step 3: Configure Environment

```bash
cp .env.example .env
# Edit .env with your tokens (same as Docker setup)
```

### Step 4: Run the Bot

```bash
# Using just
just run-local

# Or directly with Python
python -m src.main
```

---

## Add PDF Rulebooks

Place PDF rulebooks in the `rules_pdfs/` directory:

```bash
# Copy PDF files to the rules_pdfs directory
cp your_game_rulebook.pdf rules_pdfs/
```

**Naming Convention - Use English game names:**
- ✅ `Wingspan.pdf`
- ✅ `Terraforming Mars.pdf`
- ✅ `Super Fantasy Brawl.pdf`
- ❌ `Крылья.pdf` (Russian name - will work but harder to find)

---

## Common Commands

**Docker Commands:**
```bash
just logs      # View live bot logs
just down      # Stop the bot
just up        # Start the bot again
just restart   # Restart the bot (down + up)
just build     # Rebuild after code changes
```

**Development Commands:**
```bash
just test      # Run tests
just lint      # Run linter
just format    # Format code
just clean     # Remove cache files
```

**Setup Commands:**
```bash
just setup     # Setup project from scratch (creates .env, directories, installs deps)
just validate  # Validate Docker setup
```

All commands also available via `make` (e.g., `make logs`, `make test`).

---

## Stop the Bot

**Docker:**
```bash
just down  # or: make down
```

**Local:**
Press `Ctrl+C` in the terminal running the bot.

---

## Bot Commands

Once the bot is running, try these Telegram commands:

- **`/start`** - Show welcome message and usage instructions
- **`/games`** - List all available games
- **`/games <query>`** - Search for games (e.g., `/games wingspan`)

**Ask Questions:**
Just send a message in any language (English, Russian, etc.):
- "How do I attack in Gloomhaven?"
- "Как двигаться в Wingspan?"
- "What's the hand limit in Arkham Horror?"

---

## Troubleshooting

### Bot doesn't start?

**Check logs:**
```bash
just logs  # or: make logs
```

**Common issues:**
1. **Invalid tokens** - Check `.env` file has correct `TELEGRAM_TOKEN` and `OPENAI_API_KEY`
2. **Docker not running** - Ensure Docker Desktop is running
3. **Port conflicts** - Check if another container is using the same ports

### Agent not calling tools (returns "not found" without searching)?

**Issue**: Agent returns `"found": false` without actually calling search tools.

**Solution**: Use a more capable model. Edit `.env`:
```env
OPENAI_MODEL=gpt-4o-mini  # Recommended
# or
OPENAI_MODEL=gpt-4o       # Best performance
```

Then restart:
```bash
just restart  # Docker
# or press Ctrl+C and run: python -m src.main  # Local
```

See [SGR_ARCHITECTURE.md](SGR_ARCHITECTURE.md) Troubleshooting section for details.

### "No module named 'src'" error?

**Docker users:**
```bash
just build && just up
```

**Local users:**
Make sure you're running as a module:
```bash
python -m src.main  # ✅ Correct
# NOT: python src/main.py  # ❌ Wrong
```

### ugrep not found (local development)?

**Install system dependencies:**
- macOS: `brew install ugrep poppler`
- Ubuntu: `sudo apt-get install ugrep poppler-utils`
- Windows: Download from releases and add to PATH

Or use Docker instead: `just build && just up`

### Need to rebuild after code changes?

**Docker:**
```bash
just restart  # Quick restart (no rebuild)
# or
just down && just build && just up  # Full rebuild
```

**Local:**
Just restart the bot (Ctrl+C, then `python -m src.main`)

---

## What's Next?

- **Read [README.md](../README.md)** - Full project documentation and features
- **Read [DOCKER_SETUP.md](DOCKER_SETUP.md)** - Advanced Docker configuration
- **Read [SGR_ARCHITECTURE.md](SGR_ARCHITECTURE.md)** - Understand Schema-Guided Reasoning
- **Add PDF rulebooks** to `rules_pdfs/` directory
- **Configure optional settings** in `.env` (rate limits, model selection, etc.)
- **Check [CLAUDE.md](../CLAUDE.md)** if you want to modify the code

---

**Need help?** See full documentation in [README.md](../README.md) or [INDEX.md](INDEX.md)
