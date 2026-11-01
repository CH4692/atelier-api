"""Verify customer-linked intake, field persistence and historical integrity."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, select

from atelier_api.audit.models import AuditEvent
from atelier_api.repair_orders.models import RepairOrder
from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration


@pytest.fixture
def intake(auth_factory):
    client = auth_factory()
    assert sign_in(client, "employee").status_code == 200
    customer = client.post(
        "/api/v1/customers", json={"first_name": "Repair", "last_name": "Customer"}
    ).json()
    instrument = client.post(
        "/api/v1/instruments", json={"type": "violin", "customer_id": customer["id"]}
    ).json()
    payload = {
        "customer_id": customer["id"],
        "instrument_id": instrument["id"],
        "work_description": "  Replace the bridge  ",
    }
    return client, customer, instrument, payload


@pytest.mark.e2e
def test_managed_order_persists_intake_and_is_readable(intake, db_connection, accounts):
    client, customer, instrument, payload = intake
    before = datetime.now(UTC)
    response = client.post("/api/v1/repair-orders", json=payload)
    assert response.status_code == 201, response.text
    created = response.json()
    assert isinstance(created["id"], int)
    assert created["customer_id"] == customer["id"]
    assert created["instrument_id"] == instrument["id"]
    assert created["work_description"] == "Replace the bridge"
    assert created["status"] == "accepted"
    assert before <= datetime.fromisoformat(created["accepted_at"]) <= datetime.now(UTC)
    assert created["performed_at"] is None
    assert created["expected_completion_date"] is None
    assert created["internal_notes"] is None
    detail = client.get(f"/api/v1/repair-orders/{created['id']}")
    assert detail.status_code == 200
    assert detail.json() == {**created, "documents": []}
    assert client.get(f"/api/v1/instruments/{instrument['id']}/history").json()[
        "repair_orders"
    ] == [detail.json()]
    again = client.post("/api/v1/repair-orders", json=payload).json()
    assert again["id"] != created["id"]
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(RepairOrder, created["id"])
        assert stored.customer_id == customer["id"]
        assert stored.accepted_at.utcoffset().total_seconds() == 0
        events = session.exec(
            select(AuditEvent).where(
                AuditEvent.resource_type == "repair_order",
                AuditEvent.resource_id == created["id"],
            )
        ).all()
        assert len(events) == 1
        assert events[0].actor_id == accounts["employee"]
        assert events[0].action == "repair_order.created"
        assert events[0].details == {}


def test_explicit_dates_status_and_internal_notes_are_stored(intake, db_connection):
    client, _, _, payload = intake
    response = client.post(
        "/api/v1/repair-orders",
        json={
            **payload,
            "accepted_at": "2026-11-01T14:00:00+02:00",
            "expected_completion_date": "2026-11-09",
            "status": "awaiting_approval",
            "internal_notes": "  Internal estimate  ",
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert datetime.fromisoformat(created["accepted_at"]) == datetime(
        2026, 11, 1, 12, tzinfo=UTC
    )
    assert created["expected_completion_date"] == "2026-11-09"
    assert created["status"] == "awaiting_approval"
    assert created["internal_notes"] == "Internal estimate"
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert (
            session.get(RepairOrder, created["id"]).internal_notes
            == "Internal estimate"
        )


@pytest.mark.parametrize(
    "change",
    [
        {"customer_id": None},
        {"customer_id": 0},
        {"instrument_id": -1},
        {"work_description": " "},
        {"work_description": "x" * 10001},
        {"internal_notes": "x" * 10001},
        {"status": "unknown"},
        {"status": None},
        {"accepted_at": None},
        {"accepted_at": "2026-11-01T12:00:00"},
        {"expected_completion_date": "invalid"},
        {"extra": True},
    ],
)
def test_invalid_order_input_is_rejected(intake, change):
    client, _, _, payload = intake
    assert (
        client.post("/api/v1/repair-orders", json={**payload, **change}).status_code
        == 422
    )


@pytest.mark.parametrize(
    "missing", ["customer_id", "instrument_id", "work_description"]
)
def test_intake_requires_both_relationships_and_description(intake, missing):
    client, _, _, payload = intake
    data = {key: value for key, value in payload.items() if key != missing}
    assert client.post("/api/v1/repair-orders", json=data).status_code == 422


@pytest.mark.parametrize("field", ["customer_id", "instrument_id"])
def test_missing_references_return_404(intake, db_connection, field):
    client, _, _, payload = intake
    assert (
        client.post(
            "/api/v1/repair-orders", json={**payload, field: 999999}
        ).status_code
        == 404
    )
    assert db_connection.scalar(text("SELECT count(*) FROM repair_order")) == 0


def test_customer_reference_survives_ownership_and_archive_changes(intake):
    client, customer, instrument, payload = intake
    other = client.post(
        "/api/v1/customers",
        json={"first_name": "Other", "last_name": "Contracting party"},
    ).json()
    # A contracting customer is not necessarily the current owner.
    order = client.post(
        "/api/v1/repair-orders", json={**payload, "customer_id": other["id"]}
    ).json()
    assert order["customer_id"] == other["id"]
    assert (
        client.patch(
            f"/api/v1/instruments/{instrument['id']}", json={"customer_id": None}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/customers/{other['id']}/archive", json={"is_archived": True}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/instruments/{instrument['id']}/archive",
            json={"is_archived": True},
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/repair-orders/{order['id']}").json()["customer_id"]
        == other["id"]
    )
    assert client.get(f"/api/v1/customers/{customer['id']}").status_code == 200


def test_customer_and_instrument_deletion_are_blocked_without_audit_success(
    intake, db_connection
):
    client, customer, instrument, payload = intake
    order = client.post("/api/v1/repair-orders", json=payload).json()
    assert (
        client.patch(
            f"/api/v1/repair-orders/{order['id']}/archive", json={"is_archived": True}
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v1/customers/{customer['id']}").status_code == 409
    assert client.delete(f"/api/v1/instruments/{instrument['id']}").status_code == 409
    assert (
        client.get(f"/api/v1/instruments/{instrument['id']}").json()["customer_id"]
        == customer["id"]
    )
    for table, resource_id in [
        ("customer", customer["id"]),
        ("instrument", instrument["id"]),
    ]:
        with Session(
            bind=db_connection, join_transaction_mode="create_savepoint"
        ) as session:
            with pytest.raises(IntegrityError):
                session.execute(
                    text(f"DELETE FROM {table} WHERE id=:id"), {"id": resource_id}
                )
            session.rollback()
            assert not session.exec(
                select(AuditEvent).where(
                    AuditEvent.resource_id == resource_id,
                    AuditEvent.resource_type == table,
                    AuditEvent.action == f"{table}.deleted",
                )
            ).all()


@pytest.mark.parametrize(
    "assignment",
    [
        "customer_id = -1",
        "instrument_id = -1",
        "status = 'invalid'",
        "internal_notes = repeat('x', 10001)",
        "customer_id = NULL",
    ],
)
def test_database_constraints_reject_invalid_relationships_and_fields(
    intake, db_connection, assignment
):
    client, _, _, payload = intake
    order = client.post("/api/v1/repair-orders", json=payload).json()
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text(f"UPDATE repair_order SET {assignment} WHERE id=:id"),
                {"id": order["id"]},
            )
        session.rollback()


def test_intake_audit_and_order_roll_back_together(intake, db_connection, monkeypatch):
    from atelier_api.repair_orders import service

    client, _, _, payload = intake
    original = service.record_event

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise SQLAlchemyError("Simulated audit failure")

    monkeypatch.setattr(service, "record_event", fail)
    with pytest.raises(SQLAlchemyError):
        client.post("/api/v1/repair-orders", json=payload)
    assert db_connection.scalar(text("SELECT count(*) FROM repair_order")) == 0
    assert (
        db_connection.scalar(
            text("SELECT count(*) FROM audit_event WHERE resource_type='repair_order'")
        )
        == 0
    )


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_managed_orders_require_workshop_access(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        sign_in(client, role)
    assert (
        client.post(
            "/api/v1/repair-orders",
            json={
                "customer_id": 999999,
                "instrument_id": 999999,
                "work_description": "Work",
            },
        ).status_code
        == expected
    )


def test_managed_orders_require_csrf(intake):
    client, _, _, payload = intake
    assert (
        client.post(
            "/api/v1/repair-orders",
            json=payload,
            headers={"Origin": "https://attacker.example"},
        ).status_code
        == 403
    )


def test_migration_preserves_unattributed_history_and_guards_downgrade(db_connection):
    from pathlib import Path
    from uuid import uuid4

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy.exc import DBAPIError

    schema = "legacy_repair_intake_" + uuid4().hex
    db_connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    db_connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    db_connection.execute(text("CREATE TABLE customer (id integer PRIMARY KEY)"))
    db_connection.execute(
        text(
            "CREATE TABLE repair_order (id integer PRIMARY KEY, "
            "performed_at timestamptz NOT NULL, work_description text NOT NULL)"
        )
    )
    db_connection.execute(
        text(
            "CREATE TABLE repair_document (id integer PRIMARY KEY, "
            "repair_order_id integer REFERENCES repair_order(id) ON DELETE RESTRICT)"
        )
    )
    db_connection.execute(
        text(
            "INSERT INTO repair_order VALUES (10, '2025-01-01T10:00:00Z', 'Retained work')"
        )
    )
    db_connection.execute(text("INSERT INTO repair_document VALUES (20, 10)"))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("2caf51093d78")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.upgrade()
    row = db_connection.execute(
        text(
            "SELECT id, performed_at, work_description, customer_id, accepted_at, "
            "status, expected_completion_date, internal_notes FROM repair_order"
        )
    ).one()
    assert tuple(row) == (
        10,
        datetime.fromisoformat("2025-01-01T10:00:00+00:00"),
        "Retained work",
        None,
        None,
        "completed",
        None,
        None,
    )
    assert (
        db_connection.scalar(text("SELECT repair_order_id FROM repair_document")) == 10
    )
    db_connection.execute(text("INSERT INTO customer VALUES (30)"))
    db_connection.execute(
        text(
            "INSERT INTO repair_order (id, work_description, customer_id, accepted_at, status) "
            "VALUES (40, 'New intake', 30, now(), 'accepted')"
        )
    )
    assert (
        db_connection.scalar(text("SELECT performed_at FROM repair_order WHERE id=40"))
        is None
    )
    with (
        pytest.raises(DBAPIError, match="intake data would be lost"),
        db_connection.begin_nested(),
        Operations.context(MigrationContext.configure(db_connection)),
    ):
        revision.module.downgrade()
    db_connection.execute(text("DELETE FROM repair_order WHERE id=40"))
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.downgrade()
    assert (
        db_connection.scalar(
            text("SELECT work_description FROM repair_order WHERE id=10")
        )
        == "Retained work"
    )
    assert (
        db_connection.scalar(text("SELECT repair_order_id FROM repair_document")) == 10
    )
