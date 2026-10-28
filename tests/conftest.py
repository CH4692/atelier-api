"""Provide isolated API tests and load local database configuration."""

import os
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient


def pytest_configure(config: pytest.Config) -> None:
    """Load local database settings before test modules import the application.

    Exported variables, including CI configuration, take precedence over .env.
    The SQLite fallback only supports imports when no database is configured;
    PostgreSQL integration tests use TEST_DATABASE_URL exclusively.
    """
    load_dotenv(dotenv_path=config.rootpath / ".env", override=False)
    os.environ.setdefault("DATABASE_URL", "sqlite://")


@pytest.fixture
def client() -> Iterator[TestClient]:
    from atelier_api.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_session() -> Iterator[MagicMock]:
    from atelier_api.database import get_session
    from atelier_api.main import app

    session = MagicMock()
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield session
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
