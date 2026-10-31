from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlmodel import SQLModel

pytestmark = pytest.mark.integration


def test_migrations_match_registered_models(postgres_engine):
    with postgres_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, SQLModel.metadata) == []


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
        "is_archived",
    }
    assert inspector.get_pk_constraint("customer")["constrained_columns"] == ["id"]
    archive_column = next(
        column
        for column in inspector.get_columns("customer")
        if column["name"] == "is_archived"
    )
    assert archive_column["nullable"] is False
    assert archive_column["default"] is None
    columns = {column["name"]: column for column in inspector.get_columns("customer")}
    assert {
        name: columns[name]["type"].length
        for name in ("first_name", "last_name", "email", "phone")
    } == {"first_name": 100, "last_name": 100, "email": 254, "phone": 16}
    assert columns["email"]["nullable"] is True
    with postgres_engine.connect() as connection:
        versions = set(
            connection.scalars(text("SELECT version_num FROM alembic_version"))
        )
        assert versions == heads


def test_migration_creates_instrument_constraints_and_customer_reference(
    postgres_engine,
):
    inspector = inspect(postgres_engine)
    assert {column["name"] for column in inspector.get_columns("instrument")} == {
        "id",
        "type",
        "maker",
        "year_of_manufacture",
        "identification_number",
        "notes",
        "customer_id",
        "ownership",
    }
    assert inspector.get_pk_constraint("instrument")["constrained_columns"] == ["id"]
    (foreign_key,) = inspector.get_foreign_keys("instrument")
    assert foreign_key["referred_table"] == "customer"
    assert foreign_key["constrained_columns"] == ["customer_id"]
    assert foreign_key["options"]["ondelete"] == "SET NULL"
    assert {
        constraint["name"]
        for constraint in inspector.get_check_constraints("instrument")
    } == {
        "ck_instrument_type",
        "ck_instrument_ownership",
        "ck_instrument_owner_category",
        "ck_instrument_year_of_manufacture",
    }
    assert any(
        index["column_names"] == ["customer_id"]
        for index in inspector.get_indexes("instrument")
    )


def test_migration_creates_secure_session_storage(postgres_engine):
    inspector = inspect(postgres_engine)
    assert {column["name"] for column in inspector.get_columns("user_session")} == {
        "id",
        "user_id",
        "token_hash",
        "auth_version",
        "created_at",
        "last_activity_at",
        "expires_at",
        "revoked_at",
    }
    assert {column["name"] for column in inspector.get_columns("login_rate_limit")} == {
        "key_hash",
        "attempts",
        "window_started_at",
    }
    (foreign_key,) = inspector.get_foreign_keys("user_session")
    assert foreign_key["referred_table"] == "app_user"
    assert foreign_key["options"]["ondelete"] == "CASCADE"
    assert any(
        index["column_names"] == ["token_hash"] and index["unique"]
        for index in inspector.get_indexes("user_session")
    )
    timezone_columns = {
        column["name"]: column["type"].timezone
        for column in inspector.get_columns("user_session")
        if column["name"]
        in {
            "created_at",
            "last_activity_at",
            "expires_at",
            "revoked_at",
        }
    }
    assert timezone_columns == {
        "created_at": True,
        "last_activity_at": True,
        "expires_at": True,
        "revoked_at": True,
    }
