.PHONY: dev test lint lint-fix typecheck

dev:
	uv run fastapi dev

test:
	uv run pytest

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

typecheck:
	uv run mypy src
