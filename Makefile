.PHONY: dev test lint lint-fix format format-check typecheck db-migrate db-migration db-downgrade db-check

dev:
	uv run fastapi dev

test:
	uv run pytest

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy .

db-migration:
	uv run alembic revision --autogenerate -m "$(message)"

db-migrate:
	uv run alembic upgrade head

db-downgrade:
	uv run alembic downgrade -1

db-check:
	uv run alembic check
