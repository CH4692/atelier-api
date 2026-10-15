.PHONY: dev test

dev:
	uv run fastapi dev

test:
	uv run pytest
