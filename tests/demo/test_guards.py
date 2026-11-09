"""Reject accidental production and unrelated database seed targets."""

import pytest
from sqlalchemy.engine import make_url

from atelier_api.demo.service import guard_target
from atelier_api.settings import Settings


@pytest.mark.parametrize(
    "url",
    [
        "sqlite://",
        "postgresql+psycopg://localhost/atelier",
        "postgresql+psycopg://localhost/atelier_production",
    ],
)
def test_seed_target_rejects_non_disposable_databases(url):
    config = Settings(_env_file=None, database_url=url)
    with pytest.raises(ValueError, match="development mode"):
        guard_target(config)


def test_seed_target_rejects_production_even_with_demo_database_name():
    config = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://localhost/atelier_demo",
        environment="production",
        frontend_origins=["https://workshop.example.com"],
    )
    with pytest.raises(ValueError):
        guard_target(config)


def test_seed_target_checks_actual_connection_url_as_well_as_configuration():
    config = Settings(
        _env_file=None, database_url="postgresql+psycopg://localhost/atelier_demo"
    )
    guard_target(config)
    with pytest.raises(ValueError):
        guard_target(config, make_url("postgresql+psycopg://localhost/production"))
