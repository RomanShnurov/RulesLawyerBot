# ============================================
# Build Stage: Install dependencies
# ============================================
FROM python:3.13-slim AS builder

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
FROM python:3.13-slim

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

# Health check — probes the bot's own /health endpoint via stdlib urllib
# (no curl/wget in slim image). The endpoint is started by main.py once the
# asyncio loop is running; HEALTH_PORT defaults to 8080.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5).read(); sys.exit(0)"

# Run application
CMD ["python", "-m", "src.rules_lawyer_bot.main"]
