# RulesLawyerBot - Just Commands
# Run 'just' or 'just --list' to see all available commands

# Default recipe - show help
default:
    @just --list

# Install dependencies with uv
install:
    uv sync

# Build Docker image
build:
    docker-compose build

# Start bot in Docker (detached mode)
up:
    docker-compose up -d
    @echo "Bot started. View logs with: just logs"

# Stop bot
down:
    docker-compose down

# View live logs
logs:
    docker-compose logs -f app

# Restart the bot (down + up)
restart: down up

# Run tests with pytest
test:
    uv run pytest -v

# Run ruff linter
lint:
    uv run ruff check .

# Format code with ruff
format:
    uv run ruff format .

# Run linter and formatter together
check: lint format

# Clean cache files and build artifacts
clean:
    @echo "Cleaning cache files..."
    -find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    -find . -type f -name "*.pyc" -delete
    -rm -rf .pytest_cache .ruff_cache
    @echo "Clean complete!"

# Show Docker container status
status:
    docker-compose ps

# Execute command inside running container (e.g., just exec ls -la)
exec *ARGS:
    docker-compose exec app {{ARGS}}

# Open a shell inside the running container
shell:
    docker-compose exec app /bin/bash

# View Docker container logs (last 100 lines)
logs-tail:
    docker-compose logs --tail=100 app

# Build and start the bot (rebuild + up)
rebuild: build up

# Pull latest base images
pull:
    docker-compose pull

# Show environment variables (from .env)
env:
    @echo "Current environment configuration:"
    @grep -v '^#' .env 2>/dev/null || echo "No .env file found. Copy .env.example to .env"

# Validate Docker setup
validate:
    @echo "Validating Docker setup..."
    docker-compose config --quiet && echo "✅ docker-compose.yml is valid" || echo "❌ docker-compose.yml has errors"
    @test -f .env && echo "✅ .env file exists" || echo "⚠️  .env file missing (copy from .env.example)"
    @test -d rules_pdfs && echo "✅ rules_pdfs/ directory exists" || echo "⚠️  rules_pdfs/ directory missing"
    @test -d data && echo "✅ data/ directory exists" || echo "⚠️  data/ directory missing"

# Run bot locally (without Docker)
run-local:
    python -m src.main

# Setup project from scratch
setup:
    @echo "Setting up RulesLawyerBot..."
    cp .env.example .env
    @echo "✅ Created .env file - please edit it with your tokens"
    mkdir -p rules_pdfs data/sessions
    @echo "✅ Created required directories"
    just install
    @echo "✅ Installed dependencies"
    @echo ""
    @echo "Next steps:"
    @echo "1. Edit .env with your TELEGRAM_TOKEN and OPENAI_API_KEY"
    @echo "2. Run 'just build' to build Docker image"
    @echo "3. Run 'just up' to start the bot"
