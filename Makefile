.PHONY: dev test lint lint-fix typecheck db-migrate db-migration db-downgrade db-check

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

db-migration:
	uv run alembic revision --autogenerate -m "$(message)"

db-migrate:
	uv run alembic upgrade head

db-downgrade:
	uv run alembic downgrade -1

db-check:
	uv run alembic check
