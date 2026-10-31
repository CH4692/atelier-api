"""Verify durable ownership history, legacy migration and transactional consistency."""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration


@pytest.fixture
def ownership_client(auth_factory):
    client = auth_factory()
    assert sign_in(client, "employee").status_code == 200
    owners = []
    for name in ("First", "Second"):
        response = client.post(
            "/api/v1/customers", json={"first_name": name, "last_name": "Owner"}
        )
        assert response.status_code == 201
        owners.append(response.json()["id"])
    return client, owners


def test_ownership_transfer_retains_former_owners_and_actor(ownership_client, accounts):
    client, owners = ownership_client
    created = client.post(
        "/api/v1/instruments", json={"type": "violin", "customer_id": owners[0]}
    ).json()
    path = f"/api/v1/instruments/{created['id']}"
    assert created["ownership"] == "customer"
    assert client.patch(path, json={"customer_id": owners[1]}).status_code == 200
    rejected = client.patch(path, json={"ownership": "workshop"})
    assert rejected.status_code == 422
    assert client.get(path).json()["customer_id"] == owners[1]
    updated = client.patch(path, json={"ownership": "workshop", "customer_id": None})
    assert updated.status_code == 200
    assert updated.json()["ownership"] == "workshop"
    assert client.get(
        "/api/v1/instruments", params={"ownership": "workshop"}
    ).json() == [updated.json()]
    assert (
        client.get("/api/v1/instruments", params={"ownership": "customer"}).json() == []
    )
    assert (
        client.patch(
            path, json={"notes": "Changed notes", "ownership": "workshop"}
        ).status_code
        == 200
    )
    history = client.get(f"{path}/ownership-history").json()
    assert [entry["source"] for entry in history] == ["changed", "changed", "created"]
    assert [
        (
            entry["previous_ownership"],
            entry["previous_customer_id"],
            entry["ownership"],
            entry["customer_id"],
        )
        for entry in history
    ] == [
        ("customer", owners[1], "workshop", None),
        ("customer", owners[0], "customer", owners[1]),
        (None, None, "customer", owners[0]),
    ]
    for entry in history:
        assert entry["actor_id"] == accounts["employee"]
        assert datetime.fromisoformat(entry["recorded_at"]).utcoffset() == timedelta(0)
        assert "Owner" not in str(entry)
    page = client.get(f"{path}/ownership-history", params={"limit": 1, "offset": 1})
    assert page.json() == [history[1]]
    assert client.get(f"{path}/ownership-history", params={"offset": 3}).json() == []
    assert client.delete(f"/api/v1/customers/{owners[0]}").status_code == 204
    assert client.delete(path).status_code == 204
    assert client.get(f"{path}/ownership-history").json() == history


def test_customer_deletion_keeps_category_and_records_previous_owner(
    ownership_client, accounts
):
    client, owners = ownership_client
    created = client.post(
        "/api/v1/instruments", json={"type": "cello", "customer_id": owners[0]}
    ).json()
    path = f"/api/v1/instruments/{created['id']}"
    assert client.delete(f"/api/v1/customers/{owners[0]}").status_code == 204
    retained = client.get(path).json()
    assert retained["ownership"] == "customer" and retained["customer_id"] is None
    history = client.get(f"{path}/ownership-history").json()
    assert history[0]["previous_customer_id"] == owners[0]
    assert history[0]["customer_id"] is None
    assert history[0]["ownership"] == "customer"
    assert history[0]["actor_id"] == accounts["employee"]


def test_failed_history_write_rolls_back_instrument_and_audit(
    ownership_client, db_connection
):
    client, owners = ownership_client
    created = client.post(
        "/api/v1/instruments", json={"type": "viola", "customer_id": owners[0]}
    ).json()
    path = f"/api/v1/instruments/{created['id']}"
    audit_count = db_connection.scalar(text("SELECT count(*) FROM audit_event"))
    history = client.get(f"{path}/ownership-history").json()
    db_connection.execute(
        text(
            "ALTER TABLE instrument_ownership_event ADD CONSTRAINT simulated_failure CHECK (false) NOT VALID"
        )
    )
    with pytest.raises(IntegrityError):
        client.patch(path, json={"ownership": "workshop", "customer_id": None})
    assert client.get(path).json() == created
    assert client.get(f"{path}/ownership-history").json() == history
    assert db_connection.scalar(text("SELECT count(*) FROM audit_event")) == audit_count


@pytest.mark.parametrize(
    "category,owner",
    [("workshop", 1), ("unassigned", 1), ("invalid", None), (None, None)],
)
def test_database_validates_owner_categories(db_connection, category, owner):
    if owner is not None:
        owner = db_connection.scalar(
            text(
                "INSERT INTO customer (first_name, last_name, is_archived) VALUES ('Test', 'Owner', false) RETURNING id"
            )
        )
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text(
                "INSERT INTO instrument (type, ownership, customer_id) VALUES ('violin', :category, :owner)"
            ),
            {"category": category, "owner": owner},
        )


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_history_requires_workshop_access(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        sign_in(client, role)
    assert (
        client.get("/api/v1/instruments/999999/ownership-history").status_code
        == expected
    )


def test_history_has_no_write_api(ownership_client):
    client, _ = ownership_client
    instrument = client.post(
        "/api/v1/instruments", json={"type": "violin", "ownership": "workshop"}
    ).json()
    path = f"/api/v1/instruments/{instrument['id']}/ownership-history"
    before = client.get(path).json()
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(
            method, path, json={"ownership": "customer"}
        ).status_code in {404, 405}
    assert client.get(path).json() == before


def test_migration_preserves_existing_assignments_as_snapshots(db_connection):
    schema = f"legacy_ownership_{uuid4().hex}"
    db_connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    db_connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    db_connection.execute(
        text("CREATE TABLE instrument (id integer PRIMARY KEY, customer_id integer)")
    )
    db_connection.execute(text("INSERT INTO instrument VALUES (10, 7), (20, NULL)"))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("b53e84f26c01")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.upgrade()
    rows = db_connection.execute(
        text("SELECT id, customer_id, ownership FROM instrument ORDER BY id")
    ).all()
    assert rows == [(10, 7, "customer"), (20, None, "unassigned")]
    events = db_connection.execute(
        text(
            "SELECT instrument_id, source, customer_id FROM instrument_ownership_event ORDER BY instrument_id"
        )
    ).all()
    assert events == [(10, "migration", 7), (20, "migration", None)]
    db_connection.execute(
        text("UPDATE instrument SET customer_id=NULL, ownership='workshop' WHERE id=10")
    )
    assert (
        db_connection.scalar(text("SELECT count(*) FROM instrument_ownership_event"))
        == 3
    )
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.downgrade()
    assert "ownership" not in {
        column["name"] for column in inspect(db_connection).get_columns("instrument")
    }
