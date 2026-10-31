.PHONY: dev test test-fast test-integration test-e2e check test-instruments lint lint-fix format format-check typecheck db-migrate db-migration db-downgrade db-check default

TEST_WORKERS ?= 0
PYTEST_ARGS ?=

dev:
	uv run fastapi dev

test:
	uv run pytest --require-postgres -m "not external" $(PYTEST_ARGS)

test-fast:
	uv run pytest --ignore=tests/integration -m "not external" $(PYTEST_ARGS)

test-integration:
	uv run pytest tests/integration --require-postgres -m "not external" -n $(TEST_WORKERS) --dist=loadfile $(PYTEST_ARGS)

test-e2e:
	uv run pytest tests/integration --require-postgres -m "e2e and not external" $(PYTEST_ARGS)

check: lint format-check typecheck

test-instruments:
	uv run pytest tests/instruments tests/integration/test_instrument*.py tests/integration/test_customer_instruments.py

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

default: 
	git switch main
	git pull 
