"""Exercise exact item persistence, totals, edit guards and transactional audits."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session, select

from atelier_api.audit.models import AuditEvent
from atelier_api.customers.models import Customer
from atelier_api.instruments.models import Instrument
from atelier_api.repair_orders import item_service
from atelier_api.repair_orders.item_models import RepairItem
from atelier_api.repair_orders.item_schemas import RepairItemUpdate
from atelier_api.repair_orders.models import RepairOrder
from atelier_api.repair_orders.service import change_status
from atelier_api.repair_orders.statuses import RepairStatus
from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration

PAYLOAD = {
    "kind": "service",
    "description": "  Bridge fitting  ",
    "quantity": "0.5",
    "unit_price": "0.01",
}


@pytest.fixture
def repair_items(auth_factory):
    client = auth_factory()
    assert sign_in(client).status_code == 200
    customer = client.post(
        "/api/v1/customers", json={"first_name": "Repair", "last_name": "Items"}
    ).json()
    instrument = client.post(
        "/api/v1/instruments", json={"type": "violin", "customer_id": customer["id"]}
    ).json()
    order = client.post(
        "/api/v1/repairs",
        json={
            "customer_id": customer["id"],
            "instrument_id": instrument["id"],
            "work_description": "Repair",
        },
    )
    assert order.status_code == 201
    return client, order.json(), f"/api/v1/repairs/{order.json()['id']}/items"


def test_multiple_items_and_rounded_totals_persist_exactly(
    repair_items, db_connection, accounts
):
    client, order, path = repair_items
    empty = client.get(path)
    assert empty.status_code == 200
    assert empty.json() == {
        "repair_order_id": order["id"],
        "items": [],
        "service_total": "0.00",
        "material_total": "0.00",
        "total": "0.00",
    }
    created = []
    for payload in [PAYLOAD, PAYLOAD, {**PAYLOAD, "kind": "material"}]:
        response = client.post(path, json=payload)
        assert response.status_code == 201, response.text
        assert response.headers["Cache-Control"] == "private, no-store"
        row = response.json()
        assert row["description"] == "Bridge fitting"
        assert row["line_total"] == "0.01"
        assert row["repair_order_id"] == order["id"]
        created.append(row)
    summary = client.get(path)
    assert summary.json() == {
        "repair_order_id": order["id"],
        "items": created,
        "service_total": "0.02",
        "material_total": "0.01",
        "total": "0.03",
    }
    assert summary.headers["Cache-Control"] == "private, no-store"
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        rows = session.exec(select(RepairItem).order_by(RepairItem.id)).all()
        assert all(
            isinstance(row.quantity, Decimal) and isinstance(row.unit_price, Decimal)
            for row in rows
        )
        assert rows[0].quantity == Decimal("0.500")
        assert rows[0].unit_price == Decimal("0.01")
        events = session.exec(
            select(AuditEvent).where(AuditEvent.action == "repair_item.created")
        ).all()
        assert len(events) == 3
        assert {event.resource_id for event in events} == {row["id"] for row in created}
        assert all(
            event.actor_id == accounts["employee"]
            and event.resource_type == "repair_item"
            and event.succeeded
            and event.details == {"repair_order_id": order["id"]}
            for event in events
        )


@pytest.mark.parametrize(
    "change,expected_total,expected_kind",
    [
        (
            {"quantity": "3", "unit_price": "0.10", "description": " Revised "},
            "0.30",
            "service",
        ),
        ({"kind": "material"}, "0.01", "material"),
        ({"unit_price": "0"}, "0.00", "service"),
    ],
)
def test_item_patch_recalculates_totals_and_preserves_omitted_fields(
    repair_items, db_connection, accounts, change, expected_total, expected_kind
):
    client, order, path = repair_items
    before = client.post(path, json=PAYLOAD).json()
    response = client.patch(f"{path}/{before['id']}", json=change)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["line_total"] == expected_total
    assert row["kind"] == expected_kind
    assert row["description"] == (
        "Revised" if "description" in change else before["description"]
    )
    assert row["repair_order_id"] == before["repair_order_id"]
    assert row["id"] == before["id"]
    summary = client.get(path).json()
    assert summary["items"] == [row]
    assert summary["total"] == expected_total
    assert summary[expected_kind + "_total"] == expected_total
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        event = session.exec(
            select(AuditEvent).where(AuditEvent.action == "repair_item.updated")
        ).one()
        assert event.actor_id == accounts["employee"]
        assert event.resource_id == row["id"]
        assert event.details == {"repair_order_id": order["id"]}


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"description": "  Bridge fitting  "},
        {"quantity": "0.500", "unit_price": "0.010"},
    ],
)
def test_item_patch_no_op_preserves_audit(repair_items, db_connection, change):
    client, _, path = repair_items
    before = client.post(path, json=PAYLOAD).json()
    assert client.patch(f"{path}/{before['id']}", json=change).json() == before
    assert (
        db_connection.scalar(
            text("SELECT count(*) FROM audit_event WHERE action='repair_item.updated'")
        )
        == 0
    )


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_finalized_repairs_freeze_items_and_totals(repair_items, status):
    client, order, path = repair_items
    row = client.post(path, json=PAYLOAD).json()
    targets = (
        ["in_progress", "ready_for_pickup", "completed"]
        if status == "completed"
        else ["cancelled"]
    )
    for target in targets:
        assert (
            client.patch(
                f"/api/v1/repairs/{order['id']}/status", json={"status": target}
            ).status_code
            == 200
        )
    before = client.get(path).json()
    assert client.post(path, json=PAYLOAD).status_code == 409
    assert (
        client.patch(f"{path}/{row['id']}", json={"unit_price": "2.00"}).status_code
        == 409
    )
    assert client.get(path).json() == before


def test_archiving_preserves_item_access(repair_items):
    client, order, path = repair_items
    row = client.post(path, json={**PAYLOAD, "kind": "material"}).json()
    before = client.get(path).json()
    assert (
        client.patch(
            f"/api/v1/repair-orders/{order['id']}/archive", json={"is_archived": True}
        ).status_code
        == 200
    )
    assert client.get(path).json() == before
    assert before["items"] == [row]


def test_missing_repairs_and_cross_repair_items_return_404(repair_items):
    client, order, path = repair_items
    row = client.post(path, json=PAYLOAD).json()
    other = client.post(
        "/api/v1/repairs",
        json={
            "customer_id": order["customer_id"],
            "instrument_id": order["instrument_id"],
            "work_description": "Other repair",
        },
    ).json()
    other_path = f"/api/v1/repairs/{other['id']}/items"
    assert client.get(other_path).json()["total"] == "0.00"
    assert (
        client.patch(f"{other_path}/{row['id']}", json={"quantity": "2"}).status_code
        == 404
    )
    assert client.patch(f"{path}/999999", json={}).status_code == 404
    assert client.get("/api/v1/repairs/999999/items").status_code == 404
    assert client.post("/api/v1/repairs/999999/items", json=PAYLOAD).status_code == 404
    assert client.patch("/api/v1/repairs/999999/items/1", json={}).status_code == 404


@pytest.mark.parametrize("operation", ["create", "update"])
def test_item_and_audit_roll_back_together(
    repair_items, db_connection, monkeypatch, operation
):
    client, _, path = repair_items
    row = client.post(path, json=PAYLOAD).json()
    before = client.get(path).json()
    count = db_connection.scalar(text("SELECT count(*) FROM audit_event"))
    original = item_service.record_event

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Simulated audit failure")

    monkeypatch.setattr(item_service, "record_event", fail)
    with pytest.raises(RuntimeError, match="Simulated audit failure"):
        if operation == "create":
            client.post(path, json=PAYLOAD)
        else:
            client.patch(f"{path}/{row['id']}", json={"quantity": "2"})
    assert client.get(path).json() == before
    assert db_connection.scalar(text("SELECT count(*) FROM audit_event")) == count


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_item_endpoints_require_workshop_access(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        assert sign_in(client, role).status_code == 200
    path = "/api/v1/repairs/999999/items"
    assert client.get(path).status_code == expected
    assert client.post(path, json=PAYLOAD).status_code == expected
    assert client.patch(path + "/1", json={"quantity": "2"}).status_code == expected


def test_item_mutations_require_csrf(repair_items):
    client, _, path = repair_items
    row = client.post(path, json=PAYLOAD).json()
    before = client.get(path).json()
    headers = {"Origin": "https://attacker.example"}
    assert client.post(path, json=PAYLOAD, headers=headers).status_code == 403
    assert (
        client.patch(
            f"{path}/{row['id']}", json={"quantity": "2"}, headers=headers
        ).status_code
        == 403
    )
    assert client.get(path).json() == before


@pytest.mark.parametrize(
    "assignment",
    [
        "kind='invalid'",
        "description=' '",
        "quantity=0",
        "quantity=-1",
        "quantity='NaN'",
        "unit_price=-1",
        "unit_price='NaN'",
        "repair_order_id=-1",
    ],
)
def test_database_item_constraints(repair_items, db_connection, assignment):
    client, _, path = repair_items
    row = client.post(path, json=PAYLOAD).json()
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text(f"UPDATE repair_item SET {assignment} WHERE id=:id"), {"id": row["id"]}
        )
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text("DELETE FROM repair_order WHERE id=:id"),
            {"id": row["repair_order_id"]},
        )


def test_item_migration_numeric_types_and_downgrade_guard(repair_items, db_connection):
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    client, _, path = repair_items
    assert client.post(path, json=PAYLOAD).status_code == 201
    columns = {
        column["name"]: column
        for column in inspect(db_connection).get_columns("repair_item")
    }
    assert (
        columns["quantity"]["type"].precision,
        columns["quantity"]["type"].scale,
    ) == (9, 3)
    assert (
        columns["unit_price"]["type"].precision,
        columns["unit_price"]["type"].scale,
    ) == (12, 2)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("a72d90e46c15")
    assert revision is not None
    with (
        pytest.raises(DBAPIError, match="Repair items exist"),
        db_connection.begin_nested(),
        Operations.context(MigrationContext.configure(db_connection)),
    ):
        revision.module.downgrade()


def test_item_edit_waits_for_concurrent_completion(postgres_engine):
    # Use committed setup and separate connections to verify a real blocking lock.
    with Session(postgres_engine) as session:
        customer = Customer(
            first_name="Concurrent", last_name="Items", email="items@example.com"
        )
        instrument = Instrument(type="violin")
        session.add_all([customer, instrument])
        session.flush()
        order = RepairOrder(
            customer_id=customer.id,
            instrument_id=instrument.id,
            work_description="Concurrent repair",
            status=RepairStatus.READY_FOR_PICKUP,
        )
        session.add(order)
        session.flush()
        item = RepairItem(
            repair_order_id=order.id,
            kind="service",
            description="Work",
            quantity=Decimal(1),
            unit_price=Decimal("10.00"),
        )
        session.add(item)
        session.commit()
        ids = order.id, item.id, instrument.id, customer.id
    started = Event()
    finished = Event()

    def edit():
        with Session(postgres_engine) as session:
            session.execute(text("SET LOCAL statement_timeout = '5s'"))
            started.set()
            try:
                item_service.update_item(
                    session,
                    ids[0],
                    ids[1],
                    RepairItemUpdate(unit_price=Decimal("20.00")),
                )
            except HTTPException as error:
                return error.status_code
            finally:
                finished.set()
        return 200

    try:
        with (
            Session(postgres_engine) as finalizer,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            finalizer.execute(
                text("SELECT id FROM repair_order WHERE id=:id FOR UPDATE"),
                {"id": ids[0]},
            )
            future = pool.submit(edit)
            assert started.wait(timeout=2)
            assert not finished.wait(timeout=0.1)
            assert (
                change_status(finalizer, ids[0], RepairStatus.COMPLETED).status
                == RepairStatus.COMPLETED
            )
            assert future.result(timeout=5) == 409
        with Session(postgres_engine) as session:
            assert session.get(RepairItem, ids[1]).unit_price == Decimal("10.00")
            assert item_service.list_items(session, ids[0]).total == Decimal("10.00")
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM audit_event WHERE (resource_type='repair_order' AND resource_id=:repair) OR (resource_type='repair_item' AND resource_id=:item)"
                ),
                {"repair": ids[0], "item": ids[1]},
            )
            connection.execute(
                text("DELETE FROM repair_item WHERE id=:id"), {"id": ids[1]}
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
                text("DELETE FROM customer WHERE id=:id"), {"id": ids[3]}
            )
