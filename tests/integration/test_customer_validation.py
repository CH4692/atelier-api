"""Verify persisted customer constraints and safe migration of existing records."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


def test_optional_contact_and_normalized_phone_persist(postgres_client, db_connection):
    response = postgres_client.post(
        "/api/v1/customers",
        json={
            "first_name": " Maria ",
            "last_name": " Doe ",
            "phone": "0049 (176) 123-4567",
        },
    )
    assert response.status_code == 201
    customer = response.json()
    assert customer["first_name"] == "Maria" and customer["last_name"] == "Doe"
    assert customer["email"] is None and customer["phone"] == "+491761234567"
    stored = db_connection.execute(
        text("SELECT email, phone FROM customer WHERE id=:id"), {"id": customer["id"]}
    ).one()
    assert stored.email is None and stored.phone == customer["phone"]
    path = f"/api/v1/customers/{customer['id']}"
    assert (
        postgres_client.patch(path, json={"email": "maria@example.com"}).status_code
        == 200
    )
    response = postgres_client.patch(path, json={"email": " ", "phone": None})
    assert response.json()["email"] is None and response.json()["phone"] is None
    assert postgres_client.get(path).json() == response.json()


@pytest.mark.parametrize(
    "changes",
    [
        {"first_name": "\t\u00a0\u2003"},
        {"last_name": " Doe "},
        {"first_name": "a" * 101},
        {"email": "a" * 255},
        {"email": ""},
        {"phone": "0049 123"},
        {"phone": "+0123456"},
        {"phone": "123 ext 456"},
        {"phone": "1" * 16},
    ],
)
def test_database_rejects_invalid_direct_writes(db_connection, changes):
    values = {
        "first_name": "Maria",
        "last_name": "Doe",
        "email": None,
        "phone": None,
        **changes,
    }
    with pytest.raises(DBAPIError), db_connection.begin_nested():
        db_connection.execute(
            text(
                "INSERT INTO customer (first_name,last_name,email,phone,is_archived) VALUES (:first_name,:last_name,:email,:phone,false)"
            ),
            values,
        )


@pytest.fixture
def legacy_customer_database(db_connection):
    # Exercise the revision on legacy-shaped data without altering other tables.
    schema = f"legacy_validation_{uuid4().hex}"
    db_connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    db_connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    db_connection.execute(
        text(
            "CREATE TABLE customer (id integer PRIMARY KEY, first_name varchar NOT NULL, last_name varchar NOT NULL, email varchar NOT NULL, phone varchar)"
        )
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("a42d73e15b90")
    assert revision is not None
    return db_connection, revision.module


def test_migration_normalizes_legacy_data_without_changing_ids(
    legacy_customer_database,
):
    connection, revision = legacy_customer_database
    connection.execute(
        text(
            "INSERT INTO customer VALUES (42, :first, ' Doe ', ' ', '0049 (176) 123-4567')"
        ),
        {"first": "\u00a0Maria\u2003"},
    )
    with Operations.context(MigrationContext.configure(connection)):
        revision.upgrade()
    record = connection.execute(text("SELECT * FROM customer")).one()
    assert (
        record.id,
        record.first_name,
        record.last_name,
        record.email,
        record.phone,
    ) == (42, "Maria", "Doe", None, "+491761234567")
    with (
        pytest.raises(DBAPIError),
        connection.begin_nested(),
        Operations.context(MigrationContext.configure(connection)),
    ):
        revision.downgrade()


@pytest.mark.parametrize(
    "first,phone", [("a" * 101, "12345"), (" \t", "12345"), (" Maria ", "invalid")]
)
def test_migration_aborts_without_truncating_or_losing_legacy_data(
    legacy_customer_database, first, phone
):
    connection, revision = legacy_customer_database
    connection.execute(
        text(
            "INSERT INTO customer VALUES (42, :first, ' Doe ', 'maria@example.com', :phone)"
        ),
        {"first": first, "phone": phone},
    )
    with (
        pytest.raises(DBAPIError),
        connection.begin_nested(),
        Operations.context(MigrationContext.configure(connection)),
    ):
        revision.upgrade()
    record = connection.execute(text("SELECT * FROM customer")).one()
    assert (
        record.first_name == first
        and record.last_name == " Doe "
        and record.phone == phone
    )
