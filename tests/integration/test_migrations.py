from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

pytestmark = pytest.mark.integration


def test_migrations_create_customer_table_and_reach_head(postgres_engine):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    heads = set(ScriptDirectory.from_config(config).get_heads())
    inspector = inspect(postgres_engine)
    assert "customer" in inspector.get_table_names()
    assert {column["name"] for column in inspector.get_columns("customer")} == {
        "id",
        "first_name",
        "last_name",
        "email",
        "phone",
    }
    assert inspector.get_pk_constraint("customer")["constrained_columns"] == ["id"]
    with postgres_engine.connect() as connection:
        versions = set(
            connection.scalars(text("SELECT version_num FROM alembic_version"))
        )
        assert versions == heads
