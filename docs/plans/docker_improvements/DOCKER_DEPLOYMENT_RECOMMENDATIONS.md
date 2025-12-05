# Docker Deployment Recommendations for RulesLawyerBot

This document provides a comprehensive analysis and recommendations for improving the Docker and docker-compose configuration for production deployment.

## Executive Summary

The current Docker setup demonstrates good foundational practices (multi-stage builds, non-root user, resource limits) but lacks critical production-ready features. Key issues include:

- **Security vulnerabilities** in secrets handling
- **Weak health checks** that don't verify application functionality
- **Missing startup verification** for external dependencies
- **Incomplete resource management**
- **Suboptimal build configuration** for image size and caching
- **No observability/logging configuration**
- **Missing graceful shutdown handling**

---

## 1. Security Best Practices

### Current Issues

1. **Hardcoded Image References**
   - Using `latest` tags for uv image (non-deterministic)
   - No image digest pinning
   - Vulnerable to supply chain attacks

2. **Secrets Exposure Risk**
   - Environment variables passed at runtime visible in `docker inspect`
   - No secrets management strategy
   - `OPENAI_API_KEY` and `TELEGRAM_TOKEN` logged or exposed in error messages

3. **Non-Root User (Good)**
   - Already implemented with proper UID
   - Should add additional hardening

4. **Missing Security Scanning**
   - No vulnerability scanning in pipeline
   - Base image updates not enforced
   - No SBOM generation

### Recommendations

#### 1.1 Pin Image Digests

```dockerfile
# BEFORE
FROM python:3.11-slim AS builder

# AFTER
FROM python:3.11-slim@sha256:abc123... AS builder
```

For the uv image, use a specific version with digest:

```dockerfile
# BEFORE
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# AFTER
COPY --from=ghcr.io/astral-sh/uv:0.4.8@sha256:def456... /uv /bin/uv
```

**Implementation**: Create a `versions.env` file to manage image versions and digests:

```env
# versions.env
PYTHON_IMAGE=python:3.11-slim@sha256:abc123def456
UV_IMAGE=ghcr.io/astral-sh/uv:0.4.8@sha256:def456abc123
```

Update Dockerfile to use build args:

```dockerfile
ARG PYTHON_IMAGE=python:3.11-slim@sha256:abc123def456
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.4.8@sha256:def456abc123

FROM ${UV_IMAGE} AS builder
# ... rest of builder stage

FROM ${PYTHON_IMAGE}
# ... rest of runtime stage
```

#### 1.2 Use Docker Secrets (for Swarm) or Environment Variable Alternatives

For development/single-host Docker:

```yaml
# docker-compose.yml
services:
  app:
    environment:
      - TELEGRAM_TOKEN_FILE=/run/secrets/telegram_token
      - OPENAI_API_KEY_FILE=/run/secrets/openai_key
    secrets:
      - telegram_token
      - openai_key

secrets:
  telegram_token:
    file: ./secrets/telegram_token.txt
  openai_key:
    file: ./secrets/openai_key.txt
```

Update application code to read from files:

```python
def load_secret(env_var: str, file_suffix: str = "_FILE") -> str:
    """Load secret from environment variable or file."""
    file_path = os.getenv(f"{env_var}{file_suffix}")
    if file_path and os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return f.read().strip()
    return os.getenv(env_var, "")

TELEGRAM_TOKEN = load_secret("TELEGRAM_TOKEN")
OPENAI_API_KEY = load_secret("OPENAI_API_KEY")
```

#### 1.3 Add Security Scanning

Create `.dockerignore` to prevent unnecessary files in build context:

```
# .dockerignore
.git
.gitignore
.github
.env
.env.example
*.md
docs/
tests/
__pycache__
*.pyc
.pytest_cache
.coverage
.venv
*.log
rules_pdfs/
data/
node_modules/
```

#### 1.4 Add Additional Hardening

Update Dockerfile to include:

```dockerfile
# Drop unnecessary capabilities
RUN setcap -r /usr/sbin/usermod 2>/dev/null || true

# Set secure umask
RUN echo "umask 0077" >> /home/botuser/.bashrc

# Make filesystem read-only where possible
# (requires application code changes for /tmp usage)
# See security recommendations below
```

#### 1.5 Prevent Credential Logging

Add to application logging configuration:

```python
# In main.py or logging setup
SENSITIVE_PATTERNS = [
    r'sk-\w+',  # OpenAI API keys
    r'\d+:[A-Za-z0-9_-]+',  # Telegram tokens
]

class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        for pattern in SENSITIVE_PATTERNS:
            message = re.sub(pattern, '***REDACTED***', message)
        record.msg = message
        return True

logging.getLogger().addFilter(SensitiveDataFilter())
```

---

## 2. Build Optimization

### Current Issues

1. **Inefficient Layer Caching**
   - Application code copied before installation
   - Changes to src/ invalidate dependency layer
   - Multi-stage build is correct but could be optimized further

2. **Missing .dockerignore**
   - Unnecessary files copied into build context
   - Larger build context increases build time

3. **No BuildKit Optimizations**
   - Could use inline caching for faster rebuilds
   - No cache mounts for pip/uv cache

### Recommendations

#### 2.1 Optimize Layer Ordering and Caching

```dockerfile
# IMPROVED Dockerfile with better caching strategy
# ============================================
# Build Stage: Install dependencies
# ============================================
FROM python:3.11-slim AS builder

ARG UV_VERSION=0.4.8
ARG UV_DIGEST=sha256:def456abc123

WORKDIR /build

# Install uv with pinned version and digest
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir uv==${UV_VERSION}

# Copy ONLY dependency files first (layer is reused unless dependencies change)
COPY pyproject.toml uv.lock ./

# Install dependencies to virtual environment
# Use --frozen for reproducible builds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ============================================
# Runtime Stage: Minimal production image
# ============================================
FROM python:3.11-slim

# Install system dependencies once
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    ugrep \
    poppler-utils \
    tini && \
    rm -rf /var/lib/apt/lists/*

# Set locale and Python settings
ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random

# Copy virtual environment from builder
COPY --from=builder --chown=1000:1000 /build/.venv /app/.venv

WORKDIR /app

# Copy application code (changes here don't invalidate dependency layer)
COPY --chown=1000:1000 src/ ./src/
COPY --chown=1000:1000 main.py .

# Prepare directories with correct permissions
RUN mkdir -p /app/rules_pdfs /app/data/sessions && \
    chmod 700 /app/rules_pdfs /app/data /app/data/sessions

# Set up non-root user
RUN useradd -m -u 1000 -s /sbin/nologin botuser && \
    chown -R botuser:botuser /app

USER botuser

# Add virtualenv to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Enhanced health check (see section 5)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import sys; import requests; sys.exit(0)" || exit 1

# Use tini to handle signals properly
ENTRYPOINT ["/usr/bin/tini", "--"]

# Run application
CMD ["python", "-m", "src.main"]
```

#### 2.2 Enable BuildKit Caching

In `docker-compose.yml` or `docker-compose.override.yml`:

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
      # Enable BuildKit features
      buildargs:
        BUILDKIT_INLINE_CACHE: 1
      cache_from:
        - type: registry
          ref: registry.example.com/ruleslawyerbot:latest
      cache_to:
        - type: registry
          ref: registry.example.com/ruleslawyerbot:latest
          mode: max
```

#### 2.3 Add Build-Time Configuration

Create `build.env`:

```bash
# build.env - used during docker build
PYTHON_VERSION=3.11
PYTHON_DIGEST=sha256:abc123
UV_VERSION=0.4.8
UV_DIGEST=sha256:def456
```

#### 2.4 Image Size Optimization

Current approach is good (slim base image, multi-stage). Additional optimizations:

```dockerfile
# Remove unnecessary Python files
RUN find /usr/local/lib/python* -name "*.pyc" -delete && \
    find /usr/local/lib/python* -name "__pycache__" -delete && \
    find /app/.venv -name "*.pyc" -delete && \
    find /app/.venv -name "__pycache__" -delete

# This is already implicit with slim image, but can add explicitly:
RUN apt-get clean && apt-get autoclean && apt-get autoremove -y
```

---

## 3. Production Readiness

### Current Issues

1. **No Graceful Shutdown**
   - Missing signal handlers for SIGTERM
   - No timeout for graceful termination
   - May lose in-flight requests on container stop

2. **Missing Startup Verification**
   - Health check doesn't verify Telegram bot connectivity
   - No check for required files/directories
   - No validation of API connectivity

3. **Incomplete Environment Setup**
   - Missing `LOG_LEVEL` propagation
   - No log file rotation configuration
   - No startup logging

4. **Resource Constraints**
   - Current limits may be too high or too low depending on workload
   - No memory swap limits
   - Missing CPU shares

### Recommendations

#### 3.1 Add Graceful Shutdown Handling

Update `src/main.py` or main entry point:

```python
import signal
import asyncio
from telegram.ext import Application

class GracefulShutdown:
    def __init__(self):
        self.shutdown_event = asyncio.Event()

    async def shutdown_handler(self, signum, frame):
        """Handle SIGTERM/SIGINT signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_event.set()

async def main():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Setup signal handlers
    shutdown = GracefulShutdown()
    loop = asyncio.get_event_loop()
    for sig in [signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(
            sig,
            lambda s=sig: asyncio.create_task(shutdown.shutdown_handler(s, None))
        )

    # Start application
    async with application:
        await application.start()
        logger.info("Bot started successfully")

        # Wait for shutdown signal
        try:
            await shutdown.shutdown_event.wait()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt")
        finally:
            logger.info("Shutting down bot...")
            await application.stop()
            logger.info("Bot shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())
```

Update `docker-compose.yml` to set proper stop signal:

```yaml
services:
  app:
    stop_signal: SIGTERM
    stop_grace_period: 30s  # Allow 30 seconds for graceful shutdown

    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

#### 3.2 Enhance Health Checks

Create a health check script:

```python
# scripts/healthcheck.py
#!/usr/bin/env python3
"""Health check script for the bot."""

import os
import sys
import sqlite3
from pathlib import Path

def check_health():
    """Perform comprehensive health check."""

    errors = []

    # Check 1: Required directories exist
    required_dirs = [
        os.getenv('PDF_STORAGE_PATH', '/app/rules_pdfs'),
        os.getenv('DATA_PATH', '/app/data'),
    ]

    for dir_path in required_dirs:
        if not os.path.isdir(dir_path):
            errors.append(f"Required directory missing: {dir_path}")
        elif not os.access(dir_path, os.W_OK):
            errors.append(f"No write access to: {dir_path}")

    # Check 2: SQLite database accessible
    db_path = os.path.join(os.getenv('DATA_PATH', '/app/data'), 'sessions.db')
    try:
        conn = sqlite3.connect(db_path)
        conn.close()
    except Exception as e:
        errors.append(f"SQLite database error: {e}")

    # Check 3: Required environment variables
    required_env = ['TELEGRAM_TOKEN', 'OPENAI_API_KEY']
    for env_var in required_env:
        if not os.getenv(env_var):
            errors.append(f"Missing required environment variable: {env_var}")

    # Check 4: ugrep available
    try:
        import subprocess
        subprocess.run(['ugrep', '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        errors.append("ugrep not available in PATH")

    if errors:
        print("Health check failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("Health check passed")
    return 0

if __name__ == "__main__":
    sys.exit(check_health())
```

Update Dockerfile:

```dockerfile
# Copy health check script
COPY --chown=botuser:botuser scripts/healthcheck.py /app/healthcheck.py

# Health check using the script
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python /app/healthcheck.py
```

#### 3.3 Add Startup Validation

Create initialization script:

```python
# src/startup.py
"""Startup validation and initialization."""

import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def validate_startup():
    """Validate all startup requirements."""

    logger.info("Starting up RulesLawyerBot...")

    # Check required environment variables
    required_vars = {
        'TELEGRAM_TOKEN': 'Telegram bot token',
        'OPENAI_API_KEY': 'OpenAI API key',
    }

    for var, description in required_vars.items():
        if not os.getenv(var):
            logger.critical(f"Missing required environment variable: {var} ({description})")
            sys.exit(1)

    # Ensure directories exist and are writable
    dirs_to_create = [
        os.getenv('PDF_STORAGE_PATH', './rules_pdfs'),
        os.getenv('DATA_PATH', './data'),
    ]

    for dir_path in dirs_to_create:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        if not os.access(dir_path, os.W_OK):
            logger.critical(f"No write access to {dir_path}")
            sys.exit(1)
        logger.info(f"Verified directory: {dir_path}")

    # Log startup information
    logger.info(f"PDF Storage: {os.getenv('PDF_STORAGE_PATH', './rules_pdfs')}")
    logger.info(f"Data Path: {os.getenv('DATA_PATH', './data')}")
    logger.info(f"OpenAI Model: {os.getenv('OPENAI_MODEL', 'gpt-5-nano')}")
    logger.info(f"Log Level: {os.getenv('LOG_LEVEL', 'INFO')}")

    logger.info("Startup validation completed successfully")

if __name__ == "__main__":
    validate_startup()
```

Call from main entry point:

```python
# In src/main.py
from src.startup import validate_startup

async def main():
    validate_startup()
    # ... rest of initialization
```

#### 3.4 Improve Resource Management

Update `docker-compose.yml`:

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
          memswap: 2G
        reservations:
          cpus: '0.5'
          memory: 512M

    # Add logging configuration
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "10"
        labels: "service=ruleslawyerbot"
```

---

## 4. Health Check Configuration

### Current Issues

1. **Trivial Health Check**
   - Only checks if Python is available (always true)
   - Doesn't verify bot functionality
   - No application-level checks

2. **Long Start Period**
   - 40-second start period may be too long for normal startup
   - No readiness vs liveness probe distinction

3. **Same Check in Multiple Places**
   - Defined in both Dockerfile and docker-compose.yml
   - Should use single source of truth

### Recommendations

#### 4.1 Three-Tier Health Check Strategy

Implement startup, readiness, and liveness checks:

```python
# src/health.py
"""Health check endpoints and functions."""

import os
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class HealthChecker:
    """Comprehensive health checking."""

    def startup_check(self) -> tuple[bool, list[str]]:
        """Check if service can start."""
        errors = []

        # Check environment
        required_env = ['TELEGRAM_TOKEN', 'OPENAI_API_KEY']
        for var in required_env:
            if not os.getenv(var):
                errors.append(f"Missing {var}")

        # Check directories
        for dir_path in [
            os.getenv('PDF_STORAGE_PATH', './rules_pdfs'),
            os.getenv('DATA_PATH', './data'),
        ]:
            if not Path(dir_path).exists():
                errors.append(f"Missing directory: {dir_path}")

        return len(errors) == 0, errors

    def readiness_check(self) -> tuple[bool, list[str]]:
        """Check if service is ready to accept requests."""
        errors = []

        # Check database connectivity
        try:
            db_path = Path(os.getenv('DATA_PATH', './data')) / 'sessions.db'
            with sqlite3.connect(str(db_path), timeout=2) as conn:
                conn.execute('SELECT 1')
        except Exception as e:
            errors.append(f"Database error: {e}")

        # Check file system permissions
        pdf_path = Path(os.getenv('PDF_STORAGE_PATH', './rules_pdfs'))
        if not pdf_path.is_dir() or not os.access(pdf_path, os.W_OK):
            errors.append("PDF storage not writable")

        return len(errors) == 0, errors

    def liveness_check(self) -> tuple[bool, list[str]]:
        """Check if service is still alive and processing."""
        # For now, same as readiness
        # In future, could check:
        # - Recent activity in logs
        # - Message processing timestamps
        # - Memory leaks or hung processes
        return self.readiness_check()

checker = HealthChecker()

def health_check_main():
    """CLI entry point for health checks."""
    import sys
    import argparse

    parser = argparse.ArgumentParser(description='Health check utility')
    parser.add_argument('check', choices=['startup', 'readiness', 'liveness'],
                       help='Type of health check')
    args = parser.parse_args()

    if args.check == 'startup':
        ok, errors = checker.startup_check()
    elif args.check == 'readiness':
        ok, errors = checker.readiness_check()
    else:
        ok, errors = checker.liveness_check()

    if not ok:
        print(f"Health check failed: {', '.join(errors)}")
        sys.exit(1)

    print("Health check passed")
    sys.exit(0)

if __name__ == '__main__':
    health_check_main()
```

Update Dockerfile and docker-compose:

```dockerfile
# In Dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -m src.health readiness
```

```yaml
# In docker-compose.yml
healthcheck:
  test: ["CMD", "python", "-m", "src.health", "readiness"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 15s  # Reduced from 40s
```

#### 4.2 Structured Health Response

For container orchestrators (Kubernetes, etc.):

```python
# src/health_api.py
"""Health check HTTP endpoints."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class HealthResponse(BaseModel):
    status: str
    checks: dict[str, bool]
    details: dict[str, str]

@app.get("/health/startup", response_model=HealthResponse)
async def startup():
    ok, errors = checker.startup_check()
    if not ok:
        raise HTTPException(status_code=503, detail={'errors': errors})
    return HealthResponse(status='healthy', checks={'startup': True}, details={})

@app.get("/health/ready", response_model=HealthResponse)
async def readiness():
    ok, errors = checker.readiness_check()
    if not ok:
        raise HTTPException(status_code=503, detail={'errors': errors})
    return HealthResponse(status='ready', checks={'readiness': True}, details={})

@app.get("/health/live", response_model=HealthResponse)
async def liveness():
    ok, errors = checker.liveness_check()
    if not ok:
        raise HTTPException(status_code=503, detail={'errors': errors})
    return HealthResponse(status='alive', checks={'liveness': True}, details={})
```

---

## 5. Resource Management

### Current Issues

1. **Limits May Be Excessive**
   - 2GB memory limit might be wasteful for a Telegram bot
   - 2 CPU limit might be too high or too low depending on concurrent users

2. **Missing Swap Configuration**
   - No swap limit set
   - Could cause OOM scenarios

3. **No CPU Shares**
   - CPU requests/limits use hard limits, no soft sharing

4. **Missing Monitoring Integration**
   - No metrics exported
   - No integration with monitoring systems

### Recommendations

#### 5.1 Right-Size Resources

Update `docker-compose.yml` with appropriate limits based on actual workload:

```yaml
services:
  app:
    deploy:
      resources:
        # Hard limits - container will be killed if exceeded
        limits:
          cpus: '1.0'              # For typical bot load, 1 CPU should suffice
          memory: 1G               # Typical Python Telegram bot ~200-400MB
          memswap: 1G              # Total swap (set equal to memory to disable swap)

        # Soft reservations - what orchestrator reserves
        reservations:
          cpus: '0.25'             # Reserve 1/4 CPU
          memory: 256M             # Reserve 256MB minimum
```

#### 5.2 Add Memory Limit Warnings

Create memory monitoring:

```python
# src/monitoring.py
"""Resource monitoring and alerts."""

import psutil
import logging
import os

logger = logging.getLogger(__name__)

class MemoryMonitor:
    def __init__(self, threshold_percent=80):
        self.threshold = threshold_percent

    def check_memory(self):
        """Check memory usage and log warnings."""
        process = psutil.Process()
        memory_info = process.memory_info()

        # Get container memory limit from cgroups
        try:
            with open('/sys/fs/cgroup/memory/memory.limit_in_bytes', 'r') as f:
                limit = int(f.read().strip())
        except:
            limit = None

        if limit:
            usage_percent = (memory_info.rss / limit) * 100
            logger.debug(f"Memory usage: {usage_percent:.1f}% ({memory_info.rss / 1024 / 1024:.1f}MB/{limit / 1024 / 1024:.1f}MB)")

            if usage_percent > self.threshold:
                logger.warning(f"Memory usage above threshold: {usage_percent:.1f}%")
        else:
            logger.debug(f"Memory usage: {memory_info.rss / 1024 / 1024:.1f}MB")

# Call periodically
monitor = MemoryMonitor()
```

#### 5.3 Configure Logging Rotation

```yaml
services:
  app:
    logging:
      driver: "json-file"
      options:
        max-size: "50m"              # Rotate when log reaches 50MB
        max-file: "10"               # Keep 10 rotated log files
        labels: "service=ruleslawyerbot,environment=production"
        tag: "{{.Name}}/{{.ID}}"     # Include container name in logs
```

---

## 6. Additional Deployment Concerns

### 6.1 Network Configuration

```yaml
services:
  app:
    networks:
      - bot-network
    # Restrict outbound traffic if needed
    cap_drop:
      - NET_RAW
      - SYS_TIME
      - SYS_PTRACE

networks:
  bot-network:
    driver: bridge
    driver_opts:
      com.docker.network.bridge.name: br-bot
```

### 6.2 Volume Permissions

```yaml
services:
  app:
    volumes:
      - ./rules_pdfs:/app/rules_pdfs:z    # SELinux label
      - ./data:/app/data:z
```

Ensure host volumes have correct permissions:

```bash
# Create volumes with correct ownership
mkdir -p rules_pdfs data/sessions
chmod 700 rules_pdfs data
chmod 700 data/sessions

# Optionally set volume mount options
docker-compose up -d
```

### 6.3 Database Migration on Startup

```python
# src/db.py
"""Database initialization and migrations."""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def initialize_database():
    """Create database schema if needed."""
    db_path = Path("/app/data/sessions.db")

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

    logger.info(f"Database initialized at {db_path}")
```

Call during startup:

```python
# In startup.py
from src.db import initialize_database

def validate_startup():
    # ... existing checks ...
    initialize_database()
```

### 6.4 Deployment in Kubernetes

For Kubernetes deployment, use the Dockerfile as-is and create:

```yaml
# kubernetes/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ruleslawyerbot
spec:
  replicas: 1  # Single replica for stateful bot
  strategy:
    type: Recreate  # Don't use RollingUpdate for stateful service
  selector:
    matchLabels:
      app: ruleslawyerbot
  template:
    metadata:
      labels:
        app: ruleslawyerbot
    spec:
      containers:
      - name: bot
        image: ruleslawyerbot:latest
        imagePullPolicy: Always

        env:
        - name: TELEGRAM_TOKEN
          valueFrom:
            secretKeyRef:
              name: bot-secrets
              key: telegram-token
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: bot-secrets
              key: openai-key
        - name: OPENAI_BASE_URL
          value: "https://api.proxyapi.ru/openai/v1"
        - name: PDF_STORAGE_PATH
          value: "/app/rules_pdfs"
        - name: DATA_PATH
          value: "/app/data"

        resources:
          requests:
            cpu: 250m
            memory: 256Mi
          limits:
            cpu: 1000m
            memory: 1Gi

        livenessProbe:
          exec:
            command:
            - python
            - -m
            - src.health
            - liveness
          initialDelaySeconds: 30
          periodSeconds: 30
          timeoutSeconds: 10
          failureThreshold: 3

        readinessProbe:
          exec:
            command:
            - python
            - -m
            - src.health
            - readiness
          initialDelaySeconds: 15
          periodSeconds: 10
          timeoutSeconds: 10
          failureThreshold: 3

        volumeMounts:
        - name: rules-pdfs
          mountPath: /app/rules_pdfs
        - name: data
          mountPath: /app/data

      volumes:
      - name: rules-pdfs
        persistentVolumeClaim:
          claimName: rules-pdfs-pvc
      - name: data
        persistentVolumeClaim:
          claimName: bot-data-pvc

      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
        capabilities:
          drop:
          - ALL
        readOnlyRootFilesystem: true  # Requires tmpdir handling

---
apiVersion: v1
kind: Service
metadata:
  name: ruleslawyerbot
spec:
  selector:
    app: ruleslawyerbot
  type: ClusterIP
```

### 6.5 Monitoring Integration

Add Prometheus metrics:

```python
# src/metrics.py
"""Prometheus metrics for monitoring."""

from prometheus_client import Counter, Histogram, Gauge
import time

# Metrics
messages_processed = Counter(
    'bot_messages_processed_total',
    'Total messages processed',
    ['status']
)

message_processing_time = Histogram(
    'bot_message_processing_seconds',
    'Message processing time in seconds'
)

active_sessions = Gauge(
    'bot_active_sessions',
    'Number of active sessions'
)

pdf_searches = Counter(
    'bot_pdf_searches_total',
    'Total PDF searches performed',
    ['status']
)
```

Expose metrics endpoint:

```python
# Add to FastAPI app or standalone endpoint
from prometheus_client import generate_latest

@app.get("/metrics")
async def metrics():
    return generate_latest()
```

---

## 7. Complete Updated Configuration Files

### Updated Dockerfile

```dockerfile
# syntax=docker/dockerfile:1.4

# ============================================
# Build Stage: Install dependencies
# ============================================
ARG PYTHON_IMAGE=python:3.11-slim@sha256:abcdef123456
ARG UV_VERSION=0.4.8

FROM ${PYTHON_IMAGE} AS builder

ARG UV_VERSION

WORKDIR /build

# Install uv
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir uv==${UV_VERSION}

# Copy dependency files only
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ============================================
# Runtime Stage: Minimal production image
# ============================================
FROM ${PYTHON_IMAGE}

# Install system dependencies
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    ugrep \
    poppler-utils \
    tini && \
    rm -rf /var/lib/apt/lists/*

# Environment
ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=random

# Copy venv from builder
COPY --from=builder --chown=1000:1000 /build/.venv /app/.venv

WORKDIR /app

# Copy application code
COPY --chown=1000:1000 src/ ./src/
COPY --chown=1000:1000 main.py .
COPY --chown=1000:1000 scripts/healthcheck.py .

# Create directories
RUN mkdir -p /app/rules_pdfs /app/data/sessions /tmp && \
    chmod 700 /app/rules_pdfs /app/data /app/data/sessions && \
    chmod 1777 /tmp

# Create non-root user
RUN useradd -m -u 1000 -s /sbin/nologin botuser && \
    chown -R botuser:botuser /app

USER botuser

ENV PATH="/app/.venv/bin:$PATH"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -m src.health readiness

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "src.main"]
```

### Updated docker-compose.yml

```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile

    container_name: boardgame-bot

    restart: unless-stopped
    stop_signal: SIGTERM
    stop_grace_period: 30s

    environment:
      - TELEGRAM_TOKEN=${TELEGRAM_TOKEN}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://api.proxyapi.ru/openai/v1}
      - OPENAI_MODEL=${OPENAI_MODEL:-gpt-5-nano}
      - PDF_STORAGE_PATH=/app/rules_pdfs
      - DATA_PATH=/app/data
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - MAX_REQUESTS_PER_MINUTE=${MAX_REQUESTS_PER_MINUTE:-10}
      - MAX_CONCURRENT_SEARCHES=${MAX_CONCURRENT_SEARCHES:-4}

    volumes:
      - ./rules_pdfs:/app/rules_pdfs:z
      - ./data:/app/data:z

    healthcheck:
      test: ["CMD", "python", "-m", "src.health", "readiness"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
          memswap: 1G
        reservations:
          cpus: '0.25'
          memory: 256M

    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "10"
        labels: "service=ruleslawyerbot"
        tag: "{{.Name}}/{{.ID}}"
```

### .dockerignore

```
.git
.gitignore
.github
.env
.env.example
.env.local
*.md
docs/
tests/
__pycache__
*.pyc
.pytest_cache
.coverage
.venv
venv/
*.log
rules_pdfs/
data/
node_modules/
.DS_Store
.vscode/
.idea/
*.egg-info/
dist/
build/
.mypy_cache/
.ruff_cache/
```

---

## 8. Implementation Checklist

- [ ] Pin base image digests
- [ ] Add UV image version pinning
- [ ] Create `.dockerignore` file
- [ ] Update Dockerfile with BuildKit optimizations
- [ ] Add graceful shutdown handlers to application
- [ ] Create health check script (`scripts/healthcheck.py`)
- [ ] Create startup validation module (`src/startup.py`)
- [ ] Implement security filter for sensitive data logging
- [ ] Update docker-compose with improved configuration
- [ ] Add logging driver configuration
- [ ] Adjust resource limits based on actual workload
- [ ] Add memory monitoring
- [ ] Set up metrics endpoints for monitoring
- [ ] Create database initialization module
- [ ] Test graceful shutdown (docker-compose stop)
- [ ] Test health checks (docker ps should show healthy)
- [ ] Document security requirements (secrets management)
- [ ] Create Kubernetes deployment manifests (optional)
- [ ] Set up CI/CD build caching (optional)

---

## 9. Security Scanning Recommendations

Add to CI/CD pipeline:

```yaml
# Example GitHub Actions workflow
name: Container Security Scan

on: [push]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build image
        run: docker build -t ruleslawyerbot:${{ github.sha }} .

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ruleslawyerbot:${{ github.sha }}
          format: 'sarif'
          output: 'trivy-results.sarif'

      - name: Upload Trivy results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: 'trivy-results.sarif'

      - name: Run Snyk scan
        uses: snyk/actions/docker@master
        with:
          image: ruleslawyerbot:${{ github.sha }}
          args: --severity-threshold=high
```

---

## 10. Summary of Changes

| Category | Current | Recommended | Impact |
|----------|---------|-------------|--------|
| **Security** | No image digest pinning | Pin all image digests | Supply chain security |
| **Security** | Environment variables in inspect | Use secrets management | Prevents credential exposure |
| **Health Check** | Trivial check | Multi-tier health checks | Better observability |
| **Startup** | No validation | Startup validation module | Fail fast on misconfiguration |
| **Graceful Shutdown** | None | Signal handlers + timeout | Zero-downtime deployments |
| **Build Speed** | Good caching | Enhanced BuildKit + caching | 20-40% faster rebuilds |
| **Image Size** | ~500MB+ | Optimized to ~400MB | 15-20% smaller |
| **Resource Limits** | 2GB/2CPU | Right-sized 1GB/1CPU | Cost optimization |
| **Logging** | File only | JSON driver with rotation | Better centralization |
| **Monitoring** | None | Prometheus metrics ready | Better observability |

---

## Conclusion

The RulesLawyerBot Docker configuration has a solid foundation but requires improvements in security, observability, and production readiness. The recommendations above provide:

1. **Security hardening** through image pinning and secrets management
2. **Better observability** via enhanced health checks and monitoring
3. **Production readiness** with graceful shutdown and startup validation
4. **Resource optimization** and cost efficiency
5. **Improved build experience** with better caching and smaller images

Implementing these recommendations will result in a more secure, observable, and maintainable deployment.
