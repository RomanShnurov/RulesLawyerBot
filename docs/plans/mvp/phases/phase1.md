## Phase 1: Infrastructure & Docker (Days 1-2)

### 🎯 Goal
Create reproducible, optimized Docker environment with proper volume mounts.

### Step 1.1: Multi-Stage Dockerfile

**Create `Dockerfile`:**

```dockerfile
# ============================================
# Build Stage: Install dependencies
# ============================================
FROM python:3.11-slim AS builder

WORKDIR /build

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies to virtual environment
RUN uv sync --frozen --no-dev

# ============================================
# Runtime Stage: Minimal production image
# ============================================
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ugrep \
    poppler-utils && \
    rm -rf /var/lib/apt/lists/*

# Set locale for Russian filenames
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1

# Copy virtual environment from builder
COPY --from=builder /build/.venv /app/.venv

# Set working directory
WORKDIR /app

# Copy application code
COPY src/ ./src/

# Add virtualenv to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Create directories for volumes
RUN mkdir -p /app/rules_pdfs /app/data/sessions

# Run as non-root user
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app
USER botuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c 'import sys; sys.exit(0)'

# Run application
CMD ["python", "-m", "src.main"]
```

**Benefits:**
- ✅ Smaller image (~300MB vs 500MB)
- ✅ Cached dependency layer (faster rebuilds)
- ✅ Separated build/runtime dependencies
- ✅ Non-root user for security

---

### Step 1.2: Docker Compose Configuration

**Create `docker-compose.yml`:**

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: boardgame-bot
    restart: unless-stopped

    environment:
      - TELEGRAM_TOKEN=${TELEGRAM_TOKEN}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://api.proxyapi.ru/openai/v1}
      - OPENAI_MODEL=${OPENAI_MODEL:-gpt-5-nano}
      - PDF_STORAGE_PATH=/app/rules_pdfs
      - DATA_PATH=/app/data
      - LOG_LEVEL=${LOG_LEVEL:-INFO}

    volumes:
      - ./rules_pdfs:/app/rules_pdfs
      - ./data:/app/data

    healthcheck:
      test: ["CMD-SHELL", "python -c 'import sys; sys.exit(0)'"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

    # Optional: Resource limits
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

---

### Step 1.3: Environment Configuration

**Create `.env.example`:**

```ini
# Telegram Bot Configuration
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# OpenAI Configuration
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1
OPENAI_MODEL=gpt-5-nano

# Application Settings
PDF_STORAGE_PATH=/app/rules_pdfs
DATA_PATH=/app/data
LOG_LEVEL=INFO

# Rate Limiting
MAX_REQUESTS_PER_MINUTE=10
MAX_CONCURRENT_SEARCHES=4
```

**Create `.gitignore`:**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
ENV/

# Testing
.pytest_cache/
.coverage
htmlcov/

# Logs
*.log
app.log

# Data
data/
rules_pdfs/

# Environment
.env

# Ruff
.ruff_cache/

# IDE
.vscode/
.idea/
*.swp
*.swo
```

---

### Step 1.4: Makefile for Development

**Create `Makefile`:**

```makefile
.PHONY: help install build up down logs test lint format clean

help:
	@echo "Available commands:"
	@echo "  make install   - Install dependencies with uv"
	@echo "  make build     - Build Docker image"
	@echo "  make up        - Start bot in Docker"
	@echo "  make down      - Stop bot"
	@echo "  make logs      - View logs"
	@echo "  make test      - Run tests"
	@echo "  make lint      - Run ruff linter"
	@echo "  make format    - Format code with ruff"
	@echo "  make clean     - Remove cache files"

install:
	uv sync

build:
	docker-compose build

up:
	docker-compose up -d
	@echo "Bot started. View logs with: make logs"

down:
	docker-compose down

logs:
	docker-compose logs -f app

test:
	uv run pytest -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache
```

---

### Step 1.5: Verification

**Test Docker build:**

```bash
# Create .env from example
cp .env.example .env
# Edit .env with your tokens

# Test build
docker-compose build

# Verify image size
docker images boardgame-bot

# Test volume mounts
docker-compose up -d
docker exec boardgame-bot ls -la /app/rules_pdfs
docker exec boardgame-bot ls -la /app/data
docker-compose down
```

✅ **Phase 1 Complete** when:
- [ ] Docker image builds successfully (~300MB)
- [ ] Volumes mount correctly
- [ ] Environment variables load from `.env`

---
