"""Exercise repair status persistence, authorization, rollback and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session, select

from atelier_api.audit.models import AuditEvent
from atelier_api.customers.models import Customer
from atelier_api.instruments.models import Instrument
from atelier_api.repair_orders import service
from atelier_api.repair_orders.models import RepairOrder
from atelier_api.repair_orders.statuses import RepairStatus
from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration


@pytest.fixture
def repair(auth_factory):
    client = auth_factory()
    assert sign_in(client).status_code == 200
    customer = client.post(
        "/api/v1/customers",
        json={
            "first_name": "Repair",
            "last_name": "Customer",
            "email": "repair@example.com",
        },
    ).json()
    instrument = client.post(
        "/api/v1/instruments", json={"type": "violin", "customer_id": customer["id"]}
    ).json()
    response = client.post(
        "/api/v1/repairs",
        json={
            "customer_id": customer["id"],
            "instrument_id": instrument["id"],
            "work_description": "  Repair bridge  ",
            "internal_notes": "Private estimate",
        },
    )
    assert response.status_code == 201, response.text
    return client, response.json()


def transition(client, order, status):
    return client.patch(
        f"/api/v1/repairs/{order['id']}/status", json={"status": status}
    )


def test_status_lifecycle_and_timestamped_audit(repair, db_connection, accounts):
    client, initial = repair
    assert initial["status"] == "accepted"
    assert initial["accepted_at"] == initial["status_updated_at"]
    assert initial["work_description"] == "Repair bridge"
    before = initial
    targets = [
        "awaiting_approval",
        "in_progress",
        "awaiting_materials",
        "in_progress",
        "ready_for_pickup",
        "in_progress",
        "ready_for_pickup",
        "completed",
    ]
    for target in targets:
        start = datetime.now(UTC)
        response = transition(client, initial, target)
        assert response.status_code == 200, response.text
        current = response.json()
        assert current["status"] == target
        changed = datetime.fromisoformat(current["status_updated_at"])
        assert changed.utcoffset() == timedelta(0)
        assert start <= changed <= datetime.now(UTC)
        assert changed >= datetime.fromisoformat(before["status_updated_at"])
        assert {
            k: v for k, v in current.items() if k not in {"status", "status_updated_at"}
        } == {
            k: v for k, v in initial.items() if k not in {"status", "status_updated_at"}
        }
        assert client.get(f"/api/v1/repairs/{initial['id']}").json() == {
            **current,
            "documents": [],
        }
        assert response.headers["Cache-Control"] == "private, no-store"
        before = current
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        events = session.exec(
            select(AuditEvent)
            .where(AuditEvent.action == "repair_order.status_changed")
            .order_by(AuditEvent.id)
        ).all()
        assert len(events) == len(targets)
        assert [e.details for e in events] == [
            {"previous_status": previous, "new_status": target}
            for previous, target in zip(
                ["accepted", *targets[:-1]], targets, strict=True
            )
        ]
        assert all(
            e.actor_id == accounts["employee"]
            and e.resource_id == initial["id"]
            and e.resource_type == "repair_order"
            and e.succeeded
            for e in events
        )


@pytest.mark.parametrize(
    "target", ["ready_for_pickup", "completed", "awaiting_materials"]
)
def test_invalid_transition_preserves_state_and_audit(repair, db_connection, target):
    client, order = repair
    assert transition(client, order, target).status_code == 409
    assert client.get(f"/api/v1/repairs/{order['id']}").json() == {
        **order,
        "documents": [],
    }
    assert (
        db_connection.scalar(
            text(
                "SELECT count(*) FROM audit_event WHERE action='repair_order.status_changed'"
            )
        )
        == 0
    )


@pytest.mark.parametrize("state", ["accepted", "completed", "cancelled"])
def test_idempotent_retry_preserves_timestamp_and_terminal_states(
    repair, db_connection, state
):
    client, order = repair
    if state == "completed":
        for target in ["in_progress", "ready_for_pickup", "completed"]:
            response = transition(client, order, target)
            assert response.status_code == 200
            order = response.json()
    elif state == "cancelled":
        response = transition(client, order, state)
        assert response.status_code == 200
        order = response.json()
    count = db_connection.scalar(text("SELECT count(*) FROM audit_event"))
    assert transition(client, order, state).json() == order
    assert db_connection.scalar(text("SELECT count(*) FROM audit_event")) == count
    if state != "accepted":
        assert transition(client, order, "in_progress").status_code == 409
        assert db_connection.scalar(text("SELECT count(*) FROM audit_event")) == count


def test_audit_failure_rolls_back_status_and_timestamp(
    repair, db_connection, monkeypatch
):
    client, order = repair
    original = service.record_event

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Simulated audit failure")

    monkeypatch.setattr(service, "record_event", fail)
    with pytest.raises(RuntimeError, match="Simulated audit failure"):
        transition(client, order, "in_progress")
    assert client.get(f"/api/v1/repairs/{order['id']}").json() == {
        **order,
        "documents": [],
    }
    assert (
        db_connection.scalar(
            text(
                "SELECT count(*) FROM audit_event WHERE action='repair_order.status_changed'"
            )
        )
        == 0
    )


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_status_change_requires_authorized_session(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        assert sign_in(client, role).status_code == 200
    assert (
        client.patch(
            "/api/v1/repairs/999999/status", json={"status": "in_progress"}
        ).status_code
        == expected
    )
    assert client.get("/api/v1/repairs/999999").status_code == expected


def test_status_change_requires_csrf(repair):
    client, order = repair
    response = client.patch(
        f"/api/v1/repairs/{order['id']}/status",
        json={"status": "in_progress"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert client.get(f"/api/v1/repairs/{order['id']}").json() == {
        **order,
        "documents": [],
    }


@pytest.mark.parametrize("resource", ["customer", "instrument"])
def test_repair_references_prevent_history_deletion(repair, db_connection, resource):
    client, order = repair
    assert (
        client.delete(f"/api/v1/{resource}s/{order[resource + '_id']}").status_code
        == 409
    )
    assert client.get(f"/api/v1/repairs/{order['id']}").json() == {
        **order,
        "documents": [],
    }
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text(f"DELETE FROM {resource} WHERE id=:id"),
            {"id": order[resource + "_id"]},
        )


@pytest.mark.parametrize(
    "assignment",
    ["status='invalid'", "status_updated_at=accepted_at - interval '1 second'"],
)
def test_database_status_constraints(repair, db_connection, assignment):
    _, order = repair
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text(f"UPDATE repair_order SET {assignment} WHERE id=:id"),
            {"id": order["id"]},
        )


def test_status_migration_types_and_downgrade_guard(repair, db_connection):
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    columns = {
        column["name"]: column
        for column in inspect(db_connection).get_columns("repair_order")
    }
    assert columns["status_updated_at"]["type"].timezone
    assert columns["accepted_at"]["type"].timezone
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("f36b9a208d71")
    assert revision is not None
    with (
        pytest.raises(DBAPIError, match="Repair status timestamps exist"),
        db_connection.begin_nested(),
        Operations.context(MigrationContext.configure(db_connection)),
    ):
        revision.module.downgrade()


def test_concurrent_status_changes_validate_latest_committed_state(postgres_engine):
    # Real commits and separate sessions are essential: savepoint-only tests cannot
    # establish that row locks serialize concurrent transactions.
    with Session(postgres_engine) as session:
        customer = Customer(
            first_name="Concurrent", last_name="Repair", email="concurrent@example.com"
        )
        instrument = Instrument(type="violin")
        session.add_all([customer, instrument])
        session.flush()
        order = RepairOrder(
            customer_id=customer.id,
            instrument_id=instrument.id,
            work_description="Concurrency check",
            status=RepairStatus.IN_PROGRESS,
        )
        session.add(order)
        session.commit()
        ids = order.id, customer.id, instrument.id
    barrier = Barrier(2)

    def change(target):
        with Session(postgres_engine) as session:
            session.execute(text("SET LOCAL statement_timeout = '5s'"))
            barrier.wait(timeout=5)
            try:
                return service.change_status(session, ids[0], target).status
            except HTTPException as error:
                assert error.status_code == 409
                return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(change, target)
                for target in (
                    RepairStatus.READY_FOR_PICKUP,
                    RepairStatus.AWAITING_MATERIALS,
                )
            ]
            results = [future.result(timeout=10) for future in futures]
        assert results.count("conflict") == 1
        with Session(postgres_engine) as session:
            events = session.exec(
                select(AuditEvent).where(
                    AuditEvent.resource_type == "repair_order",
                    AuditEvent.resource_id == ids[0],
                    AuditEvent.action == "repair_order.status_changed",
                )
            ).all()
            assert len(events) == 1
            assert session.get(RepairOrder, ids[0]).status == next(
                r for r in results if r != "conflict"
            )
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM audit_event WHERE resource_type='repair_order' AND resource_id=:id"
                ),
                {"id": ids[0]},
            )
            connection.execute(
                text("DELETE FROM repair_order WHERE id=:id"), {"id": ids[0]}
            )
            connection.execute(
                text("DELETE FROM instrument_ownership_event WHERE instrument_id=:id"),
                {"id": ids[2]},
            )
            connection.execute(
                text("DELETE FROM instrument WHERE id=:id"), {"id": ids[2]}
            )
            connection.execute(
                text("DELETE FROM customer WHERE id=:id"), {"id": ids[1]}
            )


def test_status_migration_preserves_existing_repairs_and_documents(db_connection):
    from pathlib import Path
    from uuid import uuid4

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    schema = "legacy_repair_status_" + uuid4().hex
    db_connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    db_connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    db_connection.execute(
        text(
            "CREATE TABLE repair_order (id integer PRIMARY KEY, accepted_at timestamptz, status text NOT NULL)"
        )
    )
    db_connection.execute(
        text(
            "CREATE TABLE repair_document (id integer PRIMARY KEY, repair_order_id integer REFERENCES repair_order(id), content bytea)"
        )
    )
    db_connection.execute(
        text(
            "INSERT INTO repair_order VALUES (10, NULL, 'completed'), (20, '2026-01-01T00:00:00Z', 'in_progress')"
        )
    )
    db_connection.execute(
        text("INSERT INTO repair_document VALUES (30, 10, 'preserved')")
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("f36b9a208d71")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.upgrade()
    rows = db_connection.execute(
        text("SELECT id, status, status_updated_at FROM repair_order ORDER BY id")
    ).all()
    assert [tuple(row) for row in rows] == [
        (10, "completed", None),
        (20, "in_progress", None),
    ]
    assert (
        db_connection.scalar(text("SELECT content FROM repair_document WHERE id=30"))
        == b"preserved"
    )
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.downgrade()
    assert db_connection.scalar(text("SELECT count(*) FROM repair_order")) == 2
    assert (
        db_connection.scalar(
            text("SELECT repair_order_id FROM repair_document WHERE id=30")
        )
        == 10
    )
