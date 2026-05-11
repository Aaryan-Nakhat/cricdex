.PHONY: install dev lint format format-check check fix test clean api

install:
	uv sync

dev:
	uv sync --all-extras --group dev
	uv run playwright install chromium

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

format:
	uv run ruff format .

check: lint format-check

fix:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

api:
	uv run uvicorn cricdex.api.main:app --reload --port 8080

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
