"""Provide deterministic API tests without depending on a developer's database."""

import os
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def pytest_configure(config: pytest.Config) -> None:
    """Provide an import-only database URL before test modules load the app.

    Explicit environment configuration takes precedence. PostgreSQL integration
    tests connect only through their dedicated TEST_DATABASE_URL fixture.
    """
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
