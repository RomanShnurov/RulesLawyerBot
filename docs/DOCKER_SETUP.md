# Docker Setup Guide

This guide explains how to run RulesLawyerBot using Docker.

## Prerequisites

- Docker and Docker Compose installed
- `.env` file with your tokens (see `.env.example`)

## Quick Start

1. **Create environment file:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual tokens
   ```

2. **Build and start the bot:**
   ```bash
   make build
   make up
   ```

3. **View logs:**
   ```bash
   make logs
   ```

4. **Stop the bot:**
   ```bash
   make down
   ```

## Directory Structure

```
RulesLawyerBot/
├── src/
│   ├── __init__.py
│   └── main.py           # Main bot application
├── rules_pdfs/           # PDF storage (volume mounted)
├── data/                 # Bot data and sessions (volume mounted)
│   ├── sessions/         # SQLite session database
│   └── app.log           # Application logs
├── Dockerfile            # Multi-stage Docker build
├── docker-compose.yml    # Docker Compose configuration
├── .env.example          # Example environment variables
├── pyproject.toml        # Python dependencies
└── Makefile              # Development commands
```

## Environment Variables

See `.env.example` for all available environment variables:

- **TELEGRAM_TOKEN**: Your Telegram bot token (required)
- **OPENAI_API_KEY**: Your OpenAI API key (required)
- **OPENAI_BASE_URL**: OpenAI API endpoint (default: https://api.proxyapi.ru/openai/v1)
- **OPENAI_MODEL**: Model to use (default: gpt-5-nano)
- **PDF_STORAGE_PATH**: PDF storage directory (default: /app/rules_pdfs)
- **DATA_PATH**: Data directory (default: /app/data)
- **LOG_LEVEL**: Logging level (default: INFO)
- **MAX_REQUESTS_PER_MINUTE**: Rate limiting (default: 10)
- **MAX_CONCURRENT_SEARCHES**: Concurrent search limit (default: 4)

## Volume Mounts

The Docker setup uses two volume mounts:

1. **`./rules_pdfs:/app/rules_pdfs`**: PDF rulebooks storage
2. **`./data:/app/data`**: Bot data (sessions, logs)

These directories are created automatically and persist data between container restarts.

## Development

### Running locally without Docker

```bash
# Install dependencies
make install

# Run the bot
python -m src.main
```

### Testing

```bash
# Run tests
make test

# Run linter
make lint

# Format code
make format
```

### Cleaning up

```bash
# Remove cache files
make clean

# Stop and remove containers
make down
```

## Health Check

The container includes a health check that runs every 30 seconds. You can check the status with:

```bash
docker ps
```

Look for the health status in the STATUS column.

## Resource Limits

The Docker Compose configuration includes resource limits:

- **CPU**: 2 cores max, 0.5 cores reserved
- **Memory**: 2GB max, 512MB reserved

Adjust these in `docker-compose.yml` if needed.

## Troubleshooting

### Bot not starting

1. Check logs: `make logs`
2. Verify environment variables are set correctly in `.env`
3. Ensure TELEGRAM_TOKEN and OPENAI_API_KEY are valid

### Volume mount issues

On Windows, ensure Docker Desktop has access to the project directory:
- Open Docker Desktop → Settings → Resources → File Sharing
- Add the project directory if not already shared

### ugrep not found

The Dockerfile installs `ugrep` and `poppler-utils` in the runtime stage. If you see errors about missing `ugrep`, rebuild the image:

```bash
make build
```

## Security Notes

- The bot runs as a non-root user (`botuser`)
- Never commit `.env` file to version control
- Keep your tokens secure and rotate them regularly
- The `.env` file is excluded by `.gitignore`
