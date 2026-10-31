from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import make_url

from tests.conftest import pytest_configure
from tests.database_helpers import worker_database


@pytest.mark.parametrize(
    "url",
    [
        "sqlite://",
        "postgresql+psycopg://localhost/atelier",
        "postgresql+psycopg://localhost/production",
    ],
)
def test_worker_database_rejects_non_test_targets(url):
    with pytest.raises(ValueError), worker_database(make_url(url), "gw0"):
        pytest.fail("Unsafe database accepted")


@pytest.mark.parametrize(
    "worker", ["other", "gw", "gw-1", "gw0;drop", "gw" + "1" * 100]
)
def test_worker_database_rejects_untrusted_identifiers(worker):
    with (
        pytest.raises(ValueError),
        worker_database(
            make_url("postgresql+psycopg://localhost/atelier_test"), worker
        ),
    ):
        pytest.fail("Invalid worker accepted")


def test_serial_worker_keeps_existing_dedicated_database():
    url = make_url("postgresql+psycopg://localhost/atelier_test")
    with worker_database(url, "master") as actual:
        assert actual == url


def test_required_postgres_fails_instead_of_skipping(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_DATABASE_URL", "")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    config = MagicMock(spec=pytest.Config)
    config.rootpath = tmp_path
    config.getoption.return_value = True
    with pytest.raises(pytest.UsageError, match="TEST_DATABASE_URL is required"):
        pytest_configure(config)
