# Docker Setup Guide

Comprehensive guide for deploying RulesLawyerBot with Docker in development and production environments.

## Prerequisites

- **Docker** (20.10+) and **Docker Compose** (1.29+) installed
- `.env` file with your tokens (see `.env.example`)
- Basic understanding of Docker concepts

## Quick Start

1. **Create environment file:**
   ```bash
   cp .env.example .env
   # Edit .env with your actual tokens
   ```

2. **Build and start the bot:**
   ```bash
   just build  # or: make build
   just up     # or: make up
   ```

3. **View logs:**
   ```bash
   just logs   # or: make logs
   ```

4. **Stop the bot:**
   ```bash
   just down   # or: make down
   ```

For detailed setup instructions, see [QUICKSTART.md](QUICKSTART.md).

## Docker Architecture

### Multi-Stage Build

The Dockerfile uses a **multi-stage build** for optimal image size and security:

**Stage 1: Builder**
- Base: `python:3.13-slim`
- Installs `uv` package manager
- Copies `pyproject.toml` and `uv.lock`
- Runs `uv sync --frozen --no-dev` to install production dependencies
- Creates virtual environment at `/app/.venv`

**Stage 2: Runtime**
- Base: `python:3.13-slim`
- Installs system dependencies: `ugrep`, `poppler-utils`
- Copies virtual environment from builder stage
- Runs as non-root user (`botuser`) for security
- Exposes no ports (bot uses Telegram polling, not webhooks)

### Directory Structure

```
RulesLawyerBot/
├── src/                  # Source code (modular architecture)
│   ├── main.py           # Telegram bot entry point
│   ├── config.py         # Settings (pydantic-settings)
│   ├── agent/            # Agent definition, tools, schemas
│   ├── handlers/         # Telegram event handlers
│   ├── pipeline/         # Multi-stage pipeline logic
│   ├── formatters/       # Output formatting (SGR)
│   └── utils/            # Utilities (logger, safety, progress)
├── rules_pdfs/           # PDF storage (VOLUME MOUNTED)
├── data/                 # Bot data (VOLUME MOUNTED)
│   ├── sessions/         # Per-user SQLite session databases
│   └── app.log           # Application logs
├── Dockerfile            # Multi-stage Docker build (Python 3.13)
├── docker-compose.yml    # Docker Compose configuration
├── .dockerignore         # Files excluded from Docker context
├── .env.example          # Example environment variables
├── pyproject.toml        # Python dependencies (uv)
└── justfile / Makefile   # Development commands
```

## Environment Variables

Configuration is managed via `.env` file. See `.env.example` for template.

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `TELEGRAM_TOKEN` | Bot token from @BotFather | `1234567890:ABCdef...` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-proj-...` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_BASE_URL` | `https://api.proxyapi.ru/openai/v1` | OpenAI API endpoint |
| `OPENAI_MODEL` | `gpt-5-nano` | Model name (⚠️ use `gpt-4o-mini` or `gpt-4o` for reliable tool calling) |
| `PDF_STORAGE_PATH` | `./rules_pdfs` (local)<br>`/app/rules_pdfs` (Docker) | PDF storage directory |
| `DATA_PATH` | `./data` (local)<br>`/app/data` (Docker) | Data directory for sessions and logs |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `MAX_REQUESTS_PER_MINUTE` | `10` | Per-user rate limiting |
| `MAX_CONCURRENT_SEARCHES` | `4` | Max concurrent ugrep processes |
| `ADMIN_USER_IDS` | _(empty)_ | Comma-separated Telegram user IDs with admin access |

### Model Selection Notes

**Important**: The default model (`gpt-5-nano`) may skip tool calls. For production use:

```env
# Recommended for production
OPENAI_MODEL=gpt-4o-mini  # Best balance of cost/performance
# or
OPENAI_MODEL=gpt-4o       # Best performance, higher cost
```

See [SGR_ARCHITECTURE.md](SGR_ARCHITECTURE.md) Troubleshooting section for details.

## Volume Mounts

The `docker-compose.yml` defines two persistent volumes:

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `./rules_pdfs` | `/app/rules_pdfs` | PDF rulebook storage |
| `./data` | `/app/data` | Bot data (sessions, logs) |

**Benefits:**
- Data persists between container restarts
- Easy to backup (just copy host directories)
- PDFs can be added/removed without rebuilding container
- Logs accessible from host machine

**Volume Contents:**
```
data/
├── sessions/          # Per-user SQLite databases
│   ├── user_123456.db
│   └── user_789012.db
└── app.log            # Application logs
```

**Adding PDFs:**
```bash
# Copy PDFs to the mounted directory
cp your_game.pdf rules_pdfs/
# Bot will find them immediately (no restart needed)
```

## Development Workflow

### Building the Image

**Full build:**
```bash
just build  # or: make build
```

**Rebuild after code changes:**
```bash
just down && just build && just up
# or: just restart (doesn't rebuild - only restarts)
```

**Build with no cache (clean build):**
```bash
docker-compose build --no-cache
```

### Running the Bot

**Start in background (detached):**
```bash
just up  # or: make up
```

**Start in foreground (see logs in terminal):**
```bash
docker-compose up
```

**Restart the bot:**
```bash
just restart  # or: just down && just up
```

### Viewing Logs

**Live logs (follow):**
```bash
just logs  # or: make logs
# or: docker-compose logs -f
```

**Last N lines:**
```bash
docker-compose logs --tail=100
```

**Logs for specific time:**
```bash
docker-compose logs --since 2024-12-16T10:00:00
```

### Running Tests

**Run all tests:**
```bash
just test  # or: make test
```

**Run specific test file:**
```bash
docker-compose run --rm ruleslawyerbot pytest tests/test_tools.py -v
```

**Run tests with coverage:**
```bash
docker-compose run --rm ruleslawyerbot pytest --cov=src tests/
```

### Code Quality

**Linting:**
```bash
just lint  # or: make lint
```

**Format code:**
```bash
just format  # or: make format
```

### Cleaning Up

**Remove cache files:**
```bash
just clean  # or: make clean
```

**Stop containers:**
```bash
just down  # or: make down
```

**Remove containers, networks, and images:**
```bash
docker-compose down --rmi all --volumes
```

## Health Checks

The `docker-compose.yml` includes health checks (commented out by default):

```yaml
# healthcheck:
#   test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
#   interval: 30s
#   timeout: 10s
#   retries: 3
```

**Check container health:**
```bash
docker ps  # Look at STATUS column
docker inspect ruleslawyerbot | grep -A 10 Health
```

**Enable health checks:**
Uncomment the healthcheck section in `docker-compose.yml`.

## Resource Limits

The `docker-compose.yml` defines resource limits:

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'       # Maximum 2 CPU cores
      memory: 2G        # Maximum 2GB RAM
    reservations:
      cpus: '0.5'       # Reserve 0.5 CPU cores
      memory: 512M      # Reserve 512MB RAM
```

**Adjust for your environment:**
- **Lightweight VPS**: `cpus: '1.0'`, `memory: 1G`
- **High traffic**: `cpus: '4.0'`, `memory: 4G`

**Monitor resource usage:**
```bash
docker stats ruleslawyerbot
```

## Production Deployment

### Docker Compose for Production

**Recommended production settings in `docker-compose.yml`:**

```yaml
services:
  ruleslawyerbot:
    restart: unless-stopped  # Auto-restart on failure
    logging:
      driver: "json-file"
      options:
        max-size: "10m"      # Rotate logs at 10MB
        max-file: "3"        # Keep 3 rotated files
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
```

### Environment Configuration

**Production `.env` settings:**
```env
# Required
TELEGRAM_TOKEN=your_bot_token
OPENAI_API_KEY=your_api_key

# Recommended for production
OPENAI_MODEL=gpt-4o-mini
LOG_LEVEL=WARNING          # Reduce log volume
MAX_REQUESTS_PER_MINUTE=10
MAX_CONCURRENT_SEARCHES=4
ADMIN_USER_IDS=123456,789012  # Your admin Telegram IDs
```

### Deployment Checklist

- [ ] Set production tokens in `.env`
- [ ] Configure `OPENAI_MODEL=gpt-4o-mini` or `gpt-4o`
- [ ] Set `LOG_LEVEL=WARNING` for production
- [ ] Configure `ADMIN_USER_IDS` for admin access
- [ ] Set `restart: unless-stopped` in `docker-compose.yml`
- [ ] Configure log rotation (see above)
- [ ] Set up backup for `./data` directory (SQLite sessions)
- [ ] Set up backup for `./rules_pdfs` directory
- [ ] Monitor disk space for logs and session databases
- [ ] Test bot functionality after deployment

### Monitoring

**Check bot status:**
```bash
docker ps | grep ruleslawyerbot
```

**View resource usage:**
```bash
docker stats ruleslawyerbot
```

**Check logs for errors:**
```bash
docker-compose logs --tail=100 | grep ERROR
```

**Monitor disk space:**
```bash
du -sh data/
du -sh rules_pdfs/
```

### Backup Strategy

**Backup SQLite sessions:**
```bash
# Create backup
tar -czf backup-$(date +%Y%m%d).tar.gz data/sessions/

# Restore backup
tar -xzf backup-20241216.tar.gz
```

**Backup entire data directory:**
```bash
# Using rsync
rsync -av data/ /backup/ruleslawyerbot/data/

# Using tar
tar -czf ruleslawyerbot-data-$(date +%Y%m%d).tar.gz data/
```

## Troubleshooting

### Bot not starting

**Check logs:**
```bash
just logs  # or: docker-compose logs -f
```

**Common issues:**
1. **Invalid tokens** - Verify `TELEGRAM_TOKEN` and `OPENAI_API_KEY` in `.env`
2. **Missing `.env` file** - Run `cp .env.example .env` and edit
3. **Port conflicts** - Check if another container is using the same ports
4. **Permission issues** - Ensure `data/` and `rules_pdfs/` directories are writable

### Agent not calling tools

**Symptom**: Bot returns "not found" without actually searching PDFs.

**Solution**: Use a more capable model. Edit `.env`:
```env
OPENAI_MODEL=gpt-4o-mini  # or gpt-4o
```

Then restart:
```bash
just restart
```

See [SGR_ARCHITECTURE.md](SGR_ARCHITECTURE.md) for detailed troubleshooting.

### Volume mount issues (Windows)

**Issue**: Container can't access `rules_pdfs/` or `data/` directories.

**Solution**: Ensure Docker Desktop has access to the project directory:
1. Open Docker Desktop → Settings → Resources → File Sharing
2. Add the project directory if not already shared
3. Restart Docker Desktop

### ugrep not found

**Issue**: Error messages about missing `ugrep` command.

**Solution**: Rebuild the Docker image (ugrep is installed in Dockerfile):
```bash
just down
just build --no-cache
just up
```

### Database locked errors

**Issue**: SQLite database locked errors in logs.

**Solution**: The current implementation uses per-user session isolation (separate DB per user), which should prevent this. If you still see errors:
1. Check `data/sessions/` permissions
2. Ensure only one bot instance is running
3. Restart the bot: `just restart`

### High memory usage

**Issue**: Container using excessive memory.

**Solution**:
1. Check resource limits in `docker-compose.yml`
2. Reduce `MAX_CONCURRENT_SEARCHES` in `.env`
3. Monitor with: `docker stats ruleslawyerbot`

### Container keeps restarting

**Check exit code:**
```bash
docker ps -a | grep ruleslawyerbot
```

**View logs:**
```bash
docker-compose logs --tail=50
```

**Common causes:**
- Missing environment variables
- Invalid tokens
- Python module import errors (rebuild image)

## Security Best Practices

### Container Security

- ✅ **Runs as non-root user** (`botuser` with UID 1000)
- ✅ **Multi-stage build** (minimal runtime image, no build tools)
- ✅ **No exposed ports** (uses Telegram polling, not webhooks)
- ✅ **Read-only filesystem** (except for `/app/data` and `/app/rules_pdfs`)

### Secrets Management

- ❌ **Never commit `.env` to version control** (excluded in `.gitignore`)
- ✅ **Use strong, unique tokens**
- ✅ **Rotate tokens regularly**
- ✅ **Restrict admin access** via `ADMIN_USER_IDS`
- ✅ **Use environment variables** for all secrets

### Network Security

**For production with webhooks (future):**
- Use HTTPS for webhook endpoint
- Validate webhook requests
- Rate limit webhook endpoint
- Use Telegram's IP allowlist

## Advanced Configuration

### Using Docker Secrets (Docker Swarm)

```yaml
# docker-compose.yml
secrets:
  telegram_token:
    external: true
  openai_key:
    external: true

services:
  ruleslawyerbot:
    secrets:
      - telegram_token
      - openai_key
```

### Multi-Container Setup

For scaling across multiple instances, use Redis for rate limiting:

```yaml
services:
  ruleslawyerbot:
    # ... existing config ...
  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
volumes:
  redis-data:
```

Then update `src/utils/safety.py` to use Redis for rate limiting.

### Logging to External Service

**Using syslog driver:**
```yaml
logging:
  driver: syslog
  options:
    syslog-address: "tcp://log-server:514"
```

**Using Loki/Grafana:**
```yaml
logging:
  driver: loki
  options:
    loki-url: "http://loki:3100/loki/api/v1/push"
```
