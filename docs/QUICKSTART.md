# Quick Start Guide

Get RulesLawyerBot running in 5 minutes.

## Prerequisites

- Docker and Docker Compose installed
- Telegram bot token (from @BotFather)
- OpenAI API key

## 3-Step Setup

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

### Step 2: Build and Start

```bash
# Build the Docker image
just build  # or: make build

# Start the bot
just up     # or: make up
```

That's it! The bot is now running.

### Step 3: Verify

```bash
# View logs to confirm it started
just logs   # or: make logs
```

You should see:
```
Bot is running...
```

## Test the Bot

1. Open Telegram
2. Find your bot
3. Send `/start`
4. Ask a question about a game (if you have PDFs in `rules_pdfs/`)

## Add PDF Rulebooks

```bash
# Copy PDF files to the rules_pdfs directory
cp your_game_rulebook.pdf rules_pdfs/
```

**Tip:** Use English game names for best results:
- ✅ `Wingspan.pdf`
- ✅ `Terraforming Mars.pdf`

## Common Commands

```bash
just logs      # View bot logs
just down      # Stop the bot
just up        # Start the bot again
just build     # Rebuild after code changes
just setup     # Setup project from scratch
```

Or use `make` instead of `just` for any command.

## Stop the Bot

```bash
just down  # or: make down
```

## Troubleshooting

### Bot doesn't start?

1. Check your .env file has valid tokens
2. View logs: `just logs`
3. Ensure Docker Desktop is running

### "No module named 'src'"?

Use Docker instead: `just build && just up`

### Need to rebuild?

```bash
just down
just build
just up
# or: just rebuild
```

## What's Next?

- Read [README.md](README.md) for full documentation
- Read [DOCKER_SETUP.md](DOCKER_SETUP.md) for Docker details
- Add PDF rulebooks to `rules_pdfs/` directory
- Configure optional settings in `.env`

## Alternative: Run Without Docker

```bash
# Install dependencies
just install  # or: make install

# Run locally
python -m src.main
```

**Note:** Requires `ugrep` and `pdftotext` installed on your system.

---

**Need help?** See full documentation in [README.md](README.md)
