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


@pytest.fixture(params=["/api/v1/repairs", "/api/v1/repair-orders"])
def repair_endpoint(request):
    return request.param


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
def test_managed_order_persists_intake_and_is_readable(
    intake, db_connection, accounts, repair_endpoint
):
    client, customer, instrument, payload = intake
    before = datetime.now(UTC)
    response = client.post(repair_endpoint, json=payload)
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
    again = client.post(repair_endpoint, json=payload).json()
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


def test_explicit_dates_status_and_internal_notes_are_stored(
    intake, db_connection, repair_endpoint
):
    client, _, _, payload = intake
    response = client.post(
        repair_endpoint,
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
def test_invalid_order_input_is_rejected(intake, change, repair_endpoint):
    client, _, _, payload = intake
    assert client.post(repair_endpoint, json={**payload, **change}).status_code == 422


@pytest.mark.parametrize(
    "missing", ["customer_id", "instrument_id", "work_description"]
)
def test_intake_requires_both_relationships_and_description(
    intake, missing, repair_endpoint
):
    client, _, _, payload = intake
    data = {key: value for key, value in payload.items() if key != missing}
    assert client.post(repair_endpoint, json=data).status_code == 422


@pytest.mark.parametrize("field", ["customer_id", "instrument_id"])
def test_missing_references_return_404(intake, db_connection, field, repair_endpoint):
    client, _, _, payload = intake
    assert (
        client.post(repair_endpoint, json={**payload, field: 999999}).status_code == 404
    )
    assert db_connection.scalar(text("SELECT count(*) FROM repair_order")) == 0


def test_customer_reference_survives_ownership_and_archive_changes(
    intake, repair_endpoint
):
    client, customer, instrument, payload = intake
    other = client.post(
        "/api/v1/customers",
        json={"first_name": "Other", "last_name": "Contracting party"},
    ).json()
    # A contracting customer is not necessarily the current owner.
    order = client.post(
        repair_endpoint, json={**payload, "customer_id": other["id"]}
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
    intake, db_connection, repair_endpoint
):
    client, customer, instrument, payload = intake
    order = client.post(repair_endpoint, json=payload).json()
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
    intake, db_connection, assignment, repair_endpoint
):
    client, _, _, payload = intake
    order = client.post(repair_endpoint, json=payload).json()
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text(f"UPDATE repair_order SET {assignment} WHERE id=:id"),
                {"id": order["id"]},
            )
        session.rollback()


def test_intake_audit_and_order_roll_back_together(
    intake, db_connection, monkeypatch, repair_endpoint
):
    from atelier_api.repair_orders import service

    client, _, _, payload = intake
    original = service.record_event

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise SQLAlchemyError("Simulated audit failure")

    monkeypatch.setattr(service, "record_event", fail)
    with pytest.raises(SQLAlchemyError):
        client.post(repair_endpoint, json=payload)
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
def test_managed_orders_require_workshop_access(
    auth_factory, role, expected, repair_endpoint
):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        sign_in(client, role)
    assert (
        client.post(
            repair_endpoint,
            json={
                "customer_id": 999999,
                "instrument_id": 999999,
                "work_description": "Work",
            },
        ).status_code
        == expected
    )


def test_managed_orders_require_csrf(intake, repair_endpoint):
    client, _, _, payload = intake
    assert (
        client.post(
            repair_endpoint,
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


@pytest.fixture
def repair_listing(intake):
    client, customer, instrument, payload = intake
    other = client.post(
        "/api/v1/customers", json={"first_name": "Other", "last_name": "Customer"}
    ).json()
    orders = []
    for customer_id, status in [
        (customer["id"], "accepted"),
        (customer["id"], "in_progress"),
        (other["id"], "accepted"),
        (customer["id"], "accepted"),
    ]:
        response = client.post(
            "/api/v1/repairs",
            json={**payload, "customer_id": customer_id, "status": status},
        )
        assert response.status_code == 201
        orders.append(response.json())
    assert (
        client.patch(
            f"/api/v1/repair-orders/{orders[-1]['id']}/archive",
            json={"is_archived": True},
        ).status_code
        == 200
    )
    legacy = client.post(
        f"/api/v1/instruments/{instrument['id']}/repair-orders",
        json={
            "work_description": "Historical work",
            "performed_at": "2025-01-01T00:00:00Z",
        },
    )
    assert legacy.status_code == 201
    orders.append(legacy.json())
    return client, customer, other, orders


@pytest.mark.parametrize(
    "params,expected",
    [
        ({}, [0, 1, 2, 4]),
        ({"status": "accepted"}, [0, 2]),
        ({"status": "in_progress"}, [1]),
        ({"status": "cancelled"}, []),
        ({"customer": "first"}, [0, 1]),
        ({"customer": "other"}, [2]),
        ({"customer": "first", "status": "accepted"}, [0]),
        ({"customer_id": 999999}, []),
        ({"include_archived": True}, [0, 1, 2, 3, 4]),
        ({"include_archived": True, "customer": "first", "status": "accepted"}, [0, 3]),
        ({"offset": 1, "limit": 2}, [1, 2]),
        ({"offset": 3, "limit": 2}, [4]),
        ({"offset": 4, "limit": 2}, []),
        ({"offset": 999999}, []),
        ({"limit": 1}, [0]),
        ({"limit": 200}, [0, 1, 2, 4]),
    ],
)
def test_repair_listing_filters_and_pagination(repair_listing, params, expected):
    client, customer, other, orders = repair_listing
    query = dict(params)
    if "customer" in query:
        query["customer_id"] = {"first": customer["id"], "other": other["id"]}[
            query.pop("customer")
        ]
    response = client.get("/api/v1/repairs", params=query)
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [orders[i]["id"] for i in expected]
    assert response.headers["Cache-Control"] == "private, no-store"
    assert all("documents" not in row for row in response.json())
    unpaged = client.get(
        "/api/v1/repairs",
        params={k: v for k, v in query.items() if k not in {"offset", "limit"}},
    )
    assert response.headers["X-Total-Count"] == str(len(unpaged.json()))
    assert unpaged.headers["X-Total-Count"] == response.headers["X-Total-Count"]


@pytest.mark.parametrize("archived", [False, True])
def test_repair_detail_matches_existing_route_with_document_metadata(intake, archived):
    client, _, _, payload = intake
    order = client.post("/api/v1/repairs", json=payload).json()
    document = client.post(
        f"/api/v1/repair-orders/{order['id']}/documents?filename=estimate.pdf",
        content=b"Private estimate",
    )
    assert document.status_code == 201
    if archived:
        assert (
            client.patch(
                f"/api/v1/repair-orders/{order['id']}/archive",
                json={"is_archived": True},
            ).status_code
            == 200
        )
    detail = client.get(f"/api/v1/repairs/{order['id']}")
    assert detail.status_code == 200
    assert detail.json() == client.get(f"/api/v1/repair-orders/{order['id']}").json()
    assert detail.json()["documents"] == [document.json()]
    assert "content" not in detail.json()["documents"][0]
    assert detail.headers["Cache-Control"] == "private, no-store"


def test_empty_repair_list_and_unknown_detail(intake):
    client, _, _, _ = intake
    response = client.get("/api/v1/repairs")
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["X-Total-Count"] == "0"
    assert client.get("/api/v1/repairs/999999").status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/repairs", "/api/v1/repairs/999999"])
@pytest.mark.parametrize("role,expected", [(None, 401), ("customer", 403)])
def test_repair_reads_require_workshop_access(auth_factory, path, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        assert sign_in(client, role).status_code == 200
    assert client.get(path).status_code == expected


@pytest.mark.parametrize(
    "change,normalized",
    [
        (
            {"work_description": "  Revised bridge work  "},
            {"work_description": "Revised bridge work"},
        ),
        (
            {"expected_completion_date": "2026-12-10"},
            {"expected_completion_date": "2026-12-10"},
        ),
        (
            {"internal_notes": "  Customer requested estimate  "},
            {"internal_notes": "Customer requested estimate"},
        ),
        ({"expected_completion_date": None}, {"expected_completion_date": None}),
        ({"internal_notes": None}, {"internal_notes": None}),
        ({"internal_notes": "   "}, {"internal_notes": None}),
        (
            {
                "work_description": "Revised work",
                "expected_completion_date": None,
                "internal_notes": None,
            },
            {
                "work_description": "Revised work",
                "expected_completion_date": None,
                "internal_notes": None,
            },
        ),
    ],
)
def test_repair_patch_changes_only_supplied_fields_and_audits(
    intake, db_connection, accounts, change, normalized
):
    client, _, _, payload = intake
    before = client.post(
        "/api/v1/repairs",
        json={
            **payload,
            "expected_completion_date": "2026-12-01",
            "internal_notes": "Original notes",
        },
    ).json()
    response = client.patch(f"/api/v1/repairs/{before['id']}", json=change)
    assert response.status_code == 200, response.text
    assert response.json() == {**before, **normalized}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert client.get(f"/api/v1/repairs/{before['id']}").json() == {
        **before,
        **normalized,
        "documents": [],
    }
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(RepairOrder, before["id"])
        assert stored.work_description == response.json()["work_description"]
        assert stored.internal_notes == response.json()["internal_notes"]
        events = session.exec(
            select(AuditEvent).where(
                AuditEvent.action == "repair_order.updated",
                AuditEvent.resource_id == before["id"],
            )
        ).all()
        assert len(events) == 1
        assert events[0].actor_id == accounts["employee"]
        assert events[0].resource_type == "repair_order"
        assert events[0].succeeded is True
        expected_details = {"changed_fields": sorted(change)}
        if "expected_completion_date" in change:
            expected_details["previous_expected_completion_date"] = "2026-12-01"
            expected_details["new_expected_completion_date"] = normalized[
                "expected_completion_date"
            ]
        assert events[0].details == expected_details


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"work_description": "  Replace the bridge  "},
        {"internal_notes": None},
        {"expected_completion_date": None},
    ],
)
def test_repair_patch_no_op_does_not_write_audit(intake, db_connection, change):
    client, _, _, payload = intake
    order = client.post("/api/v1/repairs", json=payload).json()
    response = client.patch(f"/api/v1/repairs/{order['id']}", json=change)
    assert response.status_code == 200
    assert response.json() == order
    assert (
        db_connection.scalar(
            text("SELECT count(*) FROM audit_event WHERE action='repair_order.updated'")
        )
        == 0
    )


@pytest.mark.parametrize("change", [{}, {"work_description": "Updated work"}])
def test_repair_patch_unknown_order_returns_404(intake, change):
    client, _, _, _ = intake
    assert client.patch("/api/v1/repairs/999999", json=change).status_code == 404


@pytest.mark.parametrize("legacy", [False, True])
def test_repair_patch_preserves_archived_order_history_and_documents(intake, legacy):
    client, _, instrument, payload = intake
    if legacy:
        order = client.post(
            f"/api/v1/instruments/{instrument['id']}/repair-orders",
            json={
                "work_description": "Old work",
                "performed_at": "2025-01-01T00:00:00Z",
            },
        ).json()
    else:
        order = client.post("/api/v1/repairs", json=payload).json()
    document = client.post(
        f"/api/v1/repair-orders/{order['id']}/documents?filename=work.pdf",
        content=b"Historical document",
    ).json()
    assert (
        client.patch(
            f"/api/v1/repair-orders/{order['id']}/archive", json={"is_archived": True}
        ).status_code
        == 200
    )
    response = client.patch(
        f"/api/v1/repairs/{order['id']}", json={"work_description": "Corrected work"}
    )
    assert response.status_code == 200
    assert response.json() == {
        **order,
        "is_archived": True,
        "work_description": "Corrected work",
    }
    assert client.get(f"/api/v1/repairs/{order['id']}").json()["documents"] == [
        document
    ]


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_repair_patch_requires_workshop_access(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        assert sign_in(client, role).status_code == 200
    assert (
        client.patch(
            "/api/v1/repairs/999999", json={"internal_notes": "Updated"}
        ).status_code
        == expected
    )


def test_repair_patch_requires_csrf(intake):
    client, _, _, payload = intake
    order = client.post("/api/v1/repairs", json=payload).json()
    assert (
        client.patch(
            f"/api/v1/repairs/{order['id']}",
            json={"internal_notes": "Updated"},
            headers={"Origin": "https://attacker.example"},
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/repairs/{order['id']}").json()["internal_notes"] is None


def test_repair_patch_rolls_back_with_audit_failure(intake, db_connection, monkeypatch):
    from atelier_api.repair_orders import service

    client, _, _, payload = intake
    order = client.post("/api/v1/repairs", json=payload).json()
    original = service.record_event

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise SQLAlchemyError("Simulated audit failure")

    monkeypatch.setattr(service, "record_event", fail)
    with pytest.raises(SQLAlchemyError, match="Simulated audit failure"):
        client.patch(
            f"/api/v1/repairs/{order['id']}",
            json={
                "work_description": "Must roll back",
                "internal_notes": "Must roll back",
            },
        )
    assert client.get(f"/api/v1/repairs/{order['id']}").json() == {
        **order,
        "documents": [],
    }
    assert (
        db_connection.scalar(
            text("SELECT count(*) FROM audit_event WHERE action='repair_order.updated'")
        )
        == 0
    )
