"""Provide isolated API tests and load local database configuration."""

import os
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

# Tests must never inherit object-storage credentials from a developer .env.
# Empty overrides disable storage; photo tests inject an in-memory service.
for name in (
    "R2_ENDPOINT_URL",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
):
    os.environ[name] = ""
os.environ["PHOTO_AUTO_PURGE_ENABLED"] = "false"
os.environ["PHOTO_SOFT_DELETE_RETENTION_DAYS"] = "30"


def pytest_configure(config: pytest.Config) -> None:
    """Load local database settings before test modules import the application.

    Exported variables, including CI configuration, take precedence over .env.
    The SQLite fallback only supports imports when no database is configured;
    PostgreSQL integration tests use TEST_DATABASE_URL exclusively.
    """
    load_dotenv(dotenv_path=config.rootpath / ".env", override=False)
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    # Production-config fixtures must not inherit a local HTTP QR origin.
    os.environ.pop("PUBLIC_QR_BASE_URL", None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    from atelier_api.auth.dependencies import require_internal_user
    from atelier_api.main import app

    original = app.dependency_overrides.copy()
    app.dependency_overrides[require_internal_user] = lambda: None
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


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
