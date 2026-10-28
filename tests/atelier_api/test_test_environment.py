import os
from unittest.mock import MagicMock

import pytest

from tests.conftest import pytest_configure


def test_local_neon_settings_are_loaded_before_application_import(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    development = (
        "postgresql+psycopg://role:example@endpoint.neon.tech/neondb?sslmode=require"
    )
    testing = "postgresql+psycopg://role:example@endpoint.neon.tech/atelier_test?sslmode=require"
    (tmp_path / ".env").write_text(
        f"DATABASE_URL='{development}'\nTEST_DATABASE_URL='{testing}'\n"
    )
    config = MagicMock(spec=pytest.Config)
    config.rootpath = tmp_path
    pytest_configure(config)
    assert os.environ["DATABASE_URL"] == development
    assert os.environ["TEST_DATABASE_URL"] == testing


def test_ci_environment_overrides_local_database_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://localhost/ci_test")
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+psycopg://endpoint.neon.tech/neondb\n"
        "TEST_DATABASE_URL=postgresql+psycopg://endpoint.neon.tech/atelier_test\n"
    )
    config = MagicMock(spec=pytest.Config)
    config.rootpath = tmp_path
    pytest_configure(config)
    assert os.environ["DATABASE_URL"] == "sqlite://"
    assert os.environ["TEST_DATABASE_URL"] == "postgresql+psycopg://localhost/ci_test"
