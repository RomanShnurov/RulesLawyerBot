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
