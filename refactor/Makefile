.PHONY: dev test lint

dev:
	uv run uvicorn android_control.main:app --reload --port 8090

test:
	uv run pytest

lint:
	uv run ruff check src tests
