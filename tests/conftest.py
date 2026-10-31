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


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-postgres",
        action="store_true",
        help="Fail instead of skipping when TEST_DATABASE_URL is missing",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify current paths without moving tests or changing selection defaults."""
    for item in items:
        parts = item.path.relative_to(item.config.rootpath).parts
        if parts[:2] == ("tests", "integration"):
            item.add_marker(pytest.mark.integration)
        elif item.get_closest_marker("external") is None:
            if (
                isinstance(item, pytest.Function) and "client" in item.fixturenames
            ) or item.path.name in {
                "test_main.py",
                "test_multipart_limits.py",
            }:
                item.add_marker(pytest.mark.api)
            else:
                item.add_marker(pytest.mark.unit)


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
    if config.getoption(
        "require_postgres", default=False
    ) is True and not os.environ.get("TEST_DATABASE_URL"):
        raise pytest.UsageError(
            "TEST_DATABASE_URL is required; configure a dedicated PostgreSQL _test database"
        )


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
