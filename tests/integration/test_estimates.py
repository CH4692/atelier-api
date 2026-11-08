"""Verify estimate snapshots, approval attribution and independence of actual costs."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, Event

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session, select

from atelier_api.audit.models import AuditEvent
from atelier_api.customers.models import Customer
from atelier_api.estimates import service
from atelier_api.estimates.models import EstimateItem, RepairEstimate
from atelier_api.estimates.schemas import EstimateWrite
from atelier_api.estimates.statuses import EstimateStatus
from atelier_api.instruments.models import Instrument
from atelier_api.repair_orders.models import RepairOrder
from atelier_api.repair_orders.statuses import RepairStatus
from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration
LINE = {
    "kind": "service",
    "description": "  Bridge fitting  ",
    "quantity": "1",
    "unit_price": "10.00",
}
DATA = {"items": [LINE, {**LINE, "kind": "material", "unit_price": "5.00"}]}


@pytest.fixture
def estimate_data(auth_factory):
    client = auth_factory()
    assert sign_in(client).status_code == 200
    customer = client.post(
        "/api/v1/customers", json={"first_name": "Estimate", "last_name": "Customer"}
    ).json()
    instrument = client.post(
        "/api/v1/instruments", json={"type": "violin", "customer_id": customer["id"]}
    ).json()
    order = client.post(
        "/api/v1/repairs",
        json={
            "customer_id": customer["id"],
            "instrument_id": instrument["id"],
            "work_description": "Work",
        },
    ).json()
    base = f"/api/v1/repairs/{order['id']}/estimates"
    response = client.post(base, json=DATA)
    assert response.status_code == 201, response.text
    return client, order, base, response.json()


def issue(client, base, estimate):
    response = client.patch(
        f"{base}/{estimate['id']}/status", json={"status": "issued"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, base, issued):
    return client.post(
        f"{base}/{issued['id']}/approval",
        json={
            "approved_at": issued["issued_at"],
            "approval_method": "email",
            "approval_reference": "  Message reference  ",
        },
    )


def test_approved_snapshot_and_actual_costs_are_independent(
    estimate_data, db_connection, accounts
):
    client, order, base, draft = estimate_data
    assert draft["status"] == "draft"
    assert draft["revision"] == 1
    assert draft["customer_id"] == order["customer_id"]
    assert draft["created_by"] == accounts["employee"]
    assert (draft["service_total"], draft["material_total"], draft["total"]) == (
        "10.00",
        "5.00",
        "15.00",
    )
    response = approve(client, base, issue(client, base, draft))
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == "approved"
    assert approved["approval_recorded_by"] == accounts["employee"]
    assert approved["approval_method"] == "email"
    assert approved["approval_reference"] == "Message reference"
    assert datetime.fromisoformat(
        approved["approval_recorded_at"]
    ).utcoffset() == timedelta(0)
    assert datetime.fromisoformat(approved["created_at"]).utcoffset() == timedelta(0)
    actual = client.post(
        f"/api/v1/repairs/{order['id']}/items", json={**LINE, "unit_price": "32.50"}
    )
    assert actual.status_code == 201
    assert client.get(f"/api/v1/repairs/{order['id']}/items").json()["total"] == "32.50"
    newer = client.post(base, json={"items": [{**LINE, "unit_price": "20.00"}]}).json()
    assert newer["revision"] == 2
    assert newer["id"] != approved["id"]
    assert client.get(f"{base}/{approved['id']}").json() == approved
    assert client.patch(f"{base}/{approved['id']}", json=DATA).status_code == 409
    assert approve(client, base, approved).status_code == 409
    assert (
        client.get(f"{base}/{approved['id']}").headers["Cache-Control"]
        == "private, no-store"
    )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        events = session.exec(
            select(AuditEvent).where(AuditEvent.action == "repair_estimate.approved")
        ).all()
        assert len(events) == 1
        assert events[0].actor_id == accounts["employee"]
        assert events[0].resource_type == "repair_estimate"
        assert events[0].resource_id == approved["id"]
        assert events[0].details == {
            "repair_order_id": order["id"],
            "estimate_status": "approved",
            "previous_estimate_status": "issued",
        }
        assert session.get(
            RepairEstimate, approved["id"]
        ).approved_at == datetime.fromisoformat(approved["approved_at"])


def test_draft_edit_rounding_and_issued_immutability(estimate_data):
    client, _, base, draft = estimate_data
    response = client.patch(
        f"{base}/{draft['id']}",
        json={"items": [{**LINE, "quantity": "0.5", "unit_price": "0.01"}] * 3},
    )
    assert response.status_code == 200
    edited = response.json()
    assert edited["total"] == "0.03"
    assert edited["revision"] == draft["revision"]
    assert edited["created_at"] == draft["created_at"]
    issued = issue(client, base, edited)
    assert client.patch(f"{base}/{draft['id']}", json=DATA).status_code == 409
    assert client.get(f"{base}/{draft['id']}").json() == issued
    assert issue(client, base, issued) == issued


@pytest.mark.parametrize(
    "previous", ["draft", "issued", "approved", "rejected", "withdrawn"]
)
@pytest.mark.parametrize("target", ["issued", "rejected", "withdrawn"])
def test_estimate_state_machine(estimate_data, previous, target):
    client, _, base, estimate = estimate_data
    if previous in {"issued", "approved", "rejected"}:
        estimate = issue(client, base, estimate)
    if previous == "approved":
        estimate = approve(client, base, estimate).json()
    elif previous in {"rejected", "withdrawn"}:
        response = client.patch(
            f"{base}/{estimate['id']}/status", json={"status": previous}
        )
        assert response.status_code == 200
        estimate = response.json()
    allowed = previous == target or (previous, target) in {
        ("draft", "issued"),
        ("draft", "withdrawn"),
        ("issued", "rejected"),
        ("issued", "withdrawn"),
    }
    response = client.patch(f"{base}/{estimate['id']}/status", json={"status": target})
    assert response.status_code == (200 if allowed else 409)
    if not allowed or previous == target:
        assert client.get(f"{base}/{estimate['id']}").json() == estimate


@pytest.mark.parametrize("offset", [-1, 1])
def test_approval_time_must_be_within_issue_and_recording(estimate_data, offset):
    client, _, base, draft = estimate_data
    issued = issue(client, base, draft)
    when = datetime.fromisoformat(issued["issued_at"]) + timedelta(days=offset)
    response = client.post(
        f"{base}/{issued['id']}/approval",
        json={"approved_at": when.isoformat(), "approval_method": "phone"},
    )
    assert response.status_code == 422
    assert client.get(f"{base}/{issued['id']}").json() == issued


def test_approval_requires_issue_and_cannot_overwrite_first_decision(estimate_data):
    client, _, base, draft = estimate_data
    payload = {"approved_at": draft["created_at"], "approval_method": "in_person"}
    assert (
        client.post(f"{base}/{draft['id']}/approval", json=payload).status_code == 409
    )
    issued = issue(client, base, draft)
    approved = approve(client, base, issued).json()
    assert (
        client.post(f"{base}/{draft['id']}/approval", json=payload).status_code == 409
    )
    assert client.get(f"{base}/{draft['id']}").json() == approved


def test_listing_revisions_and_archival_preserve_approval(estimate_data):
    client, order, base, draft = estimate_data
    approved = approve(client, base, issue(client, base, draft)).json()
    second = client.post(base, json=DATA).json()
    listing = client.get(base, params={"offset": 1, "limit": 1})
    assert listing.status_code == 200
    assert listing.headers["X-Total-Count"] == "2"
    assert [row["id"] for row in listing.json()] == [second["id"]]
    empty = client.get(base, params={"offset": 2})
    assert empty.json() == []
    assert empty.headers["X-Total-Count"] == "2"
    for resource, identifier in [
        ("customers", order["customer_id"]),
        ("instruments", order["instrument_id"]),
        ("repair-orders", order["id"]),
    ]:
        assert (
            client.patch(
                f"/api/v1/{resource}/{identifier}/archive", json={"is_archived": True}
            ).status_code
            == 200
        )
    assert client.get(f"{base}/{draft['id']}").json() == approved
    assert client.delete(f"/api/v1/customers/{order['customer_id']}").status_code == 409


@pytest.mark.parametrize("target", ["completed", "cancelled"])
def test_terminal_repairs_keep_estimates_readable_but_block_changes(
    estimate_data, target
):
    client, order, base, draft = estimate_data
    states = (
        ["in_progress", "ready_for_pickup", "completed"]
        if target == "completed"
        else ["cancelled"]
    )
    for state in states:
        assert (
            client.patch(
                f"/api/v1/repairs/{order['id']}/status", json={"status": state}
            ).status_code
            == 200
        )
    assert client.post(base, json=DATA).status_code == 409
    assert client.patch(f"{base}/{draft['id']}", json=DATA).status_code == 409
    assert client.get(f"{base}/{draft['id']}").json() == draft


def test_cross_repair_and_unknown_references(estimate_data):
    client, order, base, draft = estimate_data
    other = client.post(
        "/api/v1/repairs",
        json={
            "customer_id": order["customer_id"],
            "instrument_id": order["instrument_id"],
            "work_description": "Other",
        },
    ).json()
    other_base = f"/api/v1/repairs/{other['id']}/estimates"
    assert client.get(other_base).json() == []
    assert client.get(f"{other_base}/{draft['id']}").status_code == 404
    assert client.patch(f"{other_base}/{draft['id']}", json=DATA).status_code == 404
    assert client.get(base + "/999999").status_code == 404
    assert client.get("/api/v1/repairs/999999/estimates").status_code == 404
    assert client.post("/api/v1/repairs/999999/estimates", json=DATA).status_code == 404


@pytest.mark.parametrize("operation", ["create", "edit", "issue", "approve"])
def test_estimate_mutation_and_audit_are_atomic(
    estimate_data, db_connection, monkeypatch, operation
):
    client, _, base, before = estimate_data
    if operation == "approve":
        before = issue(client, base, before)
    count = db_connection.scalar(text("SELECT count(*) FROM audit_event"))
    original = service.record_event

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Simulated audit failure")

    monkeypatch.setattr(service, "record_event", fail)
    with pytest.raises(RuntimeError, match="Simulated audit failure"):
        if operation == "create":
            client.post(base, json=DATA)
        elif operation == "edit":
            client.patch(
                f"{base}/{before['id']}",
                json={"items": [{**LINE, "unit_price": "999.00"}]},
            )
        elif operation == "issue":
            client.patch(f"{base}/{before['id']}/status", json={"status": "issued"})
        else:
            approve(client, base, before)
    assert client.get(f"{base}/{before['id']}").json() == before
    assert db_connection.scalar(text("SELECT count(*) FROM repair_estimate")) == 1
    assert db_connection.scalar(text("SELECT count(*) FROM audit_event")) == count


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_estimates_require_staff_authorization(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        assert sign_in(client, role).status_code == 200
    base = "/api/v1/repairs/999999/estimates"
    assert client.get(base).status_code == expected
    assert client.get(base + "/1").status_code == expected
    assert client.post(base, json=DATA).status_code == expected
    assert client.patch(base + "/1", json=DATA).status_code == expected
    assert (
        client.patch(base + "/1/status", json={"status": "issued"}).status_code
        == expected
    )
    assert (
        client.post(
            base + "/1/approval",
            json={"approved_at": "2026-01-01T00:00:00Z", "approval_method": "written"},
        ).status_code
        == expected
    )


def test_estimate_mutations_require_csrf(estimate_data):
    client, _, base, estimate = estimate_data
    headers = {"Origin": "https://attacker.example"}
    assert client.post(base, json=DATA, headers=headers).status_code == 403
    assert (
        client.patch(f"{base}/{estimate['id']}", json=DATA, headers=headers).status_code
        == 403
    )
    assert (
        client.patch(
            f"{base}/{estimate['id']}/status",
            json={"status": "issued"},
            headers=headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{base}/{estimate['id']}/approval",
            json={"approved_at": estimate["created_at"], "approval_method": "written"},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.get(f"{base}/{estimate['id']}").json() == estimate


@pytest.mark.parametrize(
    "assignment",
    ["revision=0", "status='invalid'", "status='approved'", "customer_id=-1"],
)
def test_estimate_database_constraints(estimate_data, db_connection, assignment):
    _, _, _, estimate = estimate_data
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text(f"UPDATE repair_estimate SET {assignment} WHERE id=:id"),
            {"id": estimate["id"]},
        )
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text("DELETE FROM repair_estimate WHERE id=:id"), {"id": estimate["id"]}
        )


def test_estimate_migration_refuses_to_drop_recorded_documents(
    estimate_data, db_connection
):
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("b83e71f09526")
    assert revision is not None
    with (
        pytest.raises(DBAPIError, match="Repair estimates exist"),
        db_connection.begin_nested(),
        Operations.context(MigrationContext.configure(db_connection)),
    ):
        revision.module.downgrade()


@pytest.fixture
def committed_estimate(postgres_engine):
    with Session(postgres_engine) as session:
        customer = Customer(first_name="Concurrent", last_name="Estimate")
        instrument = Instrument(type="violin")
        session.add_all([customer, instrument])
        session.flush()
        order = RepairOrder(
            customer_id=customer.id,
            instrument_id=instrument.id,
            work_description="Concurrent quote",
            status=RepairStatus.ACCEPTED,
        )
        session.add(order)
        session.commit()
        result = service.create_estimate(
            session, order.id, EstimateWrite.model_validate(DATA)
        )
        identifiers = order.id, result.id, instrument.id, customer.id
    try:
        yield identifiers
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM audit_event WHERE resource_type='repair_estimate' AND resource_id IN (SELECT id FROM repair_estimate WHERE repair_order_id=:id)"
                ),
                {"id": identifiers[0]},
            )
            connection.execute(
                text(
                    "DELETE FROM estimate_item WHERE estimate_id IN (SELECT id FROM repair_estimate WHERE repair_order_id=:id)"
                ),
                {"id": identifiers[0]},
            )
            connection.execute(
                text("DELETE FROM repair_estimate WHERE repair_order_id=:id"),
                {"id": identifiers[0]},
            )
            connection.execute(
                text("DELETE FROM repair_order WHERE id=:id"), {"id": identifiers[0]}
            )
            connection.execute(
                text("DELETE FROM instrument_ownership_event WHERE instrument_id=:id"),
                {"id": identifiers[2]},
            )
            connection.execute(
                text("DELETE FROM instrument WHERE id=:id"), {"id": identifiers[2]}
            )
            connection.execute(
                text("DELETE FROM customer WHERE id=:id"), {"id": identifiers[3]}
            )


def test_concurrent_revisions_are_unique(postgres_engine, committed_estimate):
    barrier = Barrier(2)

    def create():
        with Session(postgres_engine) as session:
            session.execute(text("SET LOCAL statement_timeout='5s'"))
            barrier.wait(timeout=5)
            return service.create_estimate(
                session, committed_estimate[0], EstimateWrite.model_validate(DATA)
            ).revision

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        assert sorted(future.result(timeout=10) for future in futures) == [2, 3]


def test_concurrent_issue_prevents_stale_draft_edit(
    postgres_engine, committed_estimate
):
    repair_id, estimate_id, _, _ = committed_estimate
    started = Event()
    finished = Event()

    def edit():
        with Session(postgres_engine) as session:
            session.execute(text("SET LOCAL statement_timeout='5s'"))
            started.set()
            try:
                service.edit_estimate(
                    session,
                    repair_id,
                    estimate_id,
                    EstimateWrite.model_validate(
                        {"items": [{**LINE, "unit_price": "999.00"}]}
                    ),
                )
            except HTTPException as error:
                return error.status_code
            finally:
                finished.set()
        return 200

    with Session(postgres_engine) as issuer, ThreadPoolExecutor(max_workers=1) as pool:
        issuer.execute(
            text("SELECT id FROM repair_order WHERE id=:id FOR UPDATE"),
            {"id": repair_id},
        )
        future = pool.submit(edit)
        assert started.wait(timeout=2)
        assert not finished.wait(timeout=0.1)
        result = service.transition_estimate(
            issuer, repair_id, estimate_id, EstimateStatus.ISSUED
        )
        assert result.total == 15
        assert future.result(timeout=10) == 409
    with Session(postgres_engine) as session:
        estimate = session.get(RepairEstimate, estimate_id)
        assert service.read_estimate(session, estimate).total == 15
        assert (
            len(
                session.exec(
                    select(EstimateItem).where(EstimateItem.estimate_id == estimate_id)
                ).all()
            )
            == 2
        )
