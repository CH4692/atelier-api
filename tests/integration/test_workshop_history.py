"""Verify dated repair history, document isolation and preservation after archival."""

from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session, select

from atelier_api.audit.models import AuditEvent
from atelier_api.repair_orders import router as repair_routes
from atelier_api.repair_orders.models import MAX_DOCUMENT_BYTES
from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration


@pytest.fixture
def history_data(auth_factory):
    client = auth_factory()
    assert sign_in(client, "employee").status_code == 200
    customer = client.post(
        "/api/v1/customers", json={"first_name": "Test", "last_name": "Owner"}
    ).json()
    instrument = client.post(
        "/api/v1/instruments", json={"type": "violin", "customer_id": customer["id"]}
    ).json()
    other = client.post("/api/v1/instruments", json={"type": "cello"}).json()
    orders = []
    for description, when in [
        ("Replaced bridge", "2026-03-01T12:00:00Z"),
        ("Repaired seam", "2025-01-01T12:00:00+02:00"),
        ("Adjusted soundpost", "2026-03-01T12:00:00Z"),
    ]:
        response = client.post(
            f"/api/v1/instruments/{instrument['id']}/repair-orders",
            json={"work_description": description, "performed_at": when},
        )
        assert response.status_code == 201
        orders.append(response.json())
    foreign = client.post(
        f"/api/v1/instruments/{other['id']}/repair-orders",
        json={
            "work_description": "Other customer's work",
            "performed_at": "2020-01-01T00:00:00Z",
        },
    ).json()
    return client, customer, instrument, orders, other, foreign


def upload(client, order, content=b"Original repair document"):
    response = client.post(
        f"/api/v1/repair-orders/{order['id']}/documents",
        params={"filename": "../../Work ü.pdf"},
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 201
    metadata = response.json()
    assert metadata["filename"] == "Work ü.pdf"
    assert metadata["size_bytes"] == len(content)
    assert metadata["sha256"] == sha256(content).hexdigest()
    assert "content" not in metadata
    return metadata


@pytest.mark.e2e
def test_history_is_chronological_and_preserves_documents_after_archiving(
    history_data, db_connection, accounts
):
    client, customer, instrument, orders, _, foreign = history_data
    document = upload(client, orders[1])
    foreign_document = upload(client, foreign, b"Private foreign repair document")
    assert (
        client.patch(
            f"/api/v1/repair-orders/{orders[1]['id']}/archive",
            json={"is_archived": True},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/customers/{customer['id']}/archive", json={"is_archived": True}
        ).status_code
        == 200
    )
    path = f"/api/v1/instruments/{instrument['id']}/history"
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "3"
    history = response.json()
    assert history["instrument"] == instrument
    assert [order["id"] for order in history["repair_orders"]] == [
        orders[1]["id"],
        orders[0]["id"],
        orders[2]["id"],
    ]
    assert history["repair_orders"][0]["work_description"] == "Repaired seam"
    assert history["repair_orders"][0]["is_archived"] is True
    assert history["repair_orders"][0]["documents"] == [document]
    assert all(order["documents"] == [] for order in history["repair_orders"][1:])
    assert foreign_document["id"] not in [
        doc["id"] for order in history["repair_orders"] for doc in order["documents"]
    ]
    for order in history["repair_orders"]:
        assert datetime.fromisoformat(order["performed_at"]).utcoffset() == timedelta(0)
    download = client.get(f"/api/v1/repair-documents/{document['id']}/content")
    assert (
        download.status_code == 200 and download.content == b"Original repair document"
    )
    assert "no-store" in download.headers["cache-control"]
    assert client.get(f"/api/v1/repair-orders/{orders[1]['id']}").json()[
        "documents"
    ] == [document]
    assert (
        client.patch(
            f"/api/v1/repair-orders/{orders[1]['id']}/archive",
            json={"is_archived": False},
        ).status_code
        == 200
    )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        events = session.exec(
            select(AuditEvent).where(
                AuditEvent.resource_type.in_(["repair_order", "repair_document"])
            )
        ).all()
        assert {event.action for event in events} >= {
            "repair_order.created",
            "repair_order.archived",
            "repair_order.restored",
            "repair_document.created",
        }
        assert all(event.actor_id == accounts["employee"] for event in events)
        assert all(
            "Repaired seam" not in event.model_dump_json()
            and "Work ü.pdf" not in event.model_dump_json()
            for event in events
        )


@pytest.mark.parametrize(
    "offset,limit,indices", [(0, 1, [1]), (1, 2, [0, 2]), (3, 2, []), (1000, 200, [])]
)
def test_history_pages_include_archived_records(history_data, offset, limit, indices):
    client, _, instrument, orders, _, _ = history_data
    response = client.get(
        f"/api/v1/instruments/{instrument['id']}/history",
        params={"offset": offset, "limit": limit},
    )
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "3"
    assert [entry["id"] for entry in response.json()["repair_orders"]] == [
        orders[index]["id"] for index in indices
    ]


def test_referenced_instrument_and_repair_cannot_be_deleted(
    history_data, db_connection
):
    client, _, instrument, orders, _, _ = history_data
    document = upload(client, orders[0])
    before = db_connection.scalar(text("SELECT count(*) FROM audit_event"))
    assert client.delete(f"/api/v1/instruments/{instrument['id']}").status_code == 409
    assert client.get(f"/api/v1/instruments/{instrument['id']}").json() == instrument
    assert db_connection.scalar(text("SELECT count(*) FROM audit_event")) == before
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text("DELETE FROM repair_order WHERE id=:id"), {"id": orders[0]["id"]}
        )
    assert (
        client.get(f"/api/v1/repair-documents/{document['id']}/content").status_code
        == 200
    )


@pytest.mark.parametrize("operation", ["repair", "document"])
def test_audit_failure_rolls_back_repair_and_document(
    history_data, db_connection, monkeypatch, operation
):
    client, _, instrument, orders, _, _ = history_data
    counts = [
        db_connection.scalar(text(f"SELECT count(*) FROM {table}"))
        for table in ("repair_order", "repair_document", "audit_event")
    ]
    original = repair_routes.record_event

    def append_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Simulated audit failure")

    monkeypatch.setattr(repair_routes, "record_event", append_then_fail)
    with pytest.raises(RuntimeError, match="Simulated audit failure"):
        if operation == "repair":
            client.post(
                f"/api/v1/instruments/{instrument['id']}/repair-orders",
                json={
                    "work_description": "Must roll back",
                    "performed_at": "2026-01-01T00:00:00Z",
                },
            )
        else:
            client.post(
                f"/api/v1/repair-orders/{orders[0]['id']}/documents?filename=rollback.pdf",
                content=b"Must roll back",
            )
    assert [
        db_connection.scalar(text(f"SELECT count(*) FROM {table}"))
        for table in ("repair_order", "repair_document", "audit_event")
    ] == counts


def test_document_size_boundary_is_persisted_and_downloaded(history_data):
    client, _, _, orders, _, _ = history_data
    content = b"x" * MAX_DOCUMENT_BYTES
    document = upload(client, orders[0], content)
    assert (
        client.get(f"/api/v1/repair-documents/{document['id']}/content").content
        == content
    )
    assert (
        client.post(
            f"/api/v1/repair-orders/{orders[0]['id']}/documents?filename=too-large.pdf",
            content=content + b"x",
        ).status_code
        == 413
    )


@pytest.mark.parametrize(
    "size,digest,content",
    [(0, "a" * 64, b""), (1, "a" * 64, b"xx"), (1, "invalid", b"x")],
)
def test_database_validates_document_metadata(
    history_data, db_connection, size, digest, content
):
    _, _, _, orders, _, _ = history_data
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text(
                "INSERT INTO repair_document (repair_order_id, filename, size_bytes, sha256, content, created_at) VALUES (:order, 'test.pdf', :size, :digest, :content, now())"
            ),
            {
                "order": orders[0]["id"],
                "size": size,
                "digest": digest,
                "content": content,
            },
        )


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_all_history_and_document_routes_require_workshop_access(
    auth_factory, role, expected
):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        sign_in(client, role)
    assert client.get("/api/v1/instruments/999999/history").status_code == expected
    assert client.get("/api/v1/repair-orders/999999").status_code == expected
    assert client.get("/api/v1/repair-documents/999999/content").status_code == expected
    assert (
        client.post(
            "/api/v1/instruments/999999/repair-orders",
            json={"work_description": "Work", "performed_at": "2026-01-01T00:00:00Z"},
        ).status_code
        == expected
    )
    assert (
        client.patch(
            "/api/v1/repair-orders/999999/archive", json={"is_archived": True}
        ).status_code
        == expected
    )
    assert (
        client.post(
            "/api/v1/repair-orders/999999/documents?filename=test.pdf",
            content=b"document",
        ).status_code
        == expected
    )


def test_downgrade_refuses_to_discard_work_and_documents(history_data, db_connection):
    client, _, _, orders, _, _ = history_data
    document = upload(client, orders[0])
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("d75a06b48e23")
    assert revision is not None
    with (
        pytest.raises(DBAPIError),
        db_connection.begin_nested(),
        Operations.context(MigrationContext.configure(db_connection)),
    ):
        revision.module.downgrade()
    assert (
        client.get(f"/api/v1/repair-documents/{document['id']}/content").status_code
        == 200
    )
