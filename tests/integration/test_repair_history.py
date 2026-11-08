"""Verify repair-scoped audit history, privacy, attribution and transactional reads."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from atelier_api.audit.models import AuditAction, AuditEvent, AuditResource
from atelier_api.audit.service import purge_expired_events, record_event
from atelier_api.repair_orders import service as repair_service
from atelier_api.users.authentication import authenticate_user
from atelier_api.users.service import set_user_active
from tests.integration.auth_helpers import PASSWORD, sign_in

pytestmark = pytest.mark.integration


@pytest.fixture
def history_order(auth_factory):
    client = auth_factory(customer_portal_auth_enabled=True)
    assert sign_in(client).status_code == 200
    customer = client.post(
        "/api/v1/customers", json={"first_name": "History", "last_name": "Customer"}
    ).json()
    instrument = client.post(
        "/api/v1/instruments", json={"type": "violin", "customer_id": customer["id"]}
    ).json()
    response = client.post(
        "/api/v1/repairs",
        json={
            "customer_id": customer["id"],
            "instrument_id": instrument["id"],
            "work_description": "Private repair description",
            "internal_notes": "Private internal note",
        },
    )
    assert response.status_code == 201
    order = response.json()
    return client, order, f"/api/v1/repairs/{order['id']}/history"


def test_history_records_fields_statuses_dates_and_responsible_users(
    history_order, accounts
):
    client, order, path = history_order
    assert (
        client.patch(
            f"/api/v1/repairs/{order['id']}",
            json={
                "work_description": "Revised private description",
                "internal_notes": "Revised private note",
                "expected_completion_date": "2026-12-01",
            },
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/repairs/{order['id']}/status", json={"status": "in_progress"}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/repairs/{order['id']}", json={"expected_completion_date": None}
        ).status_code
        == 200
    )
    assert sign_in(client, "admin").status_code == 200
    response = client.get(path)
    assert response.status_code == 200, response.text
    events = response.json()
    assert [event["action"] for event in events] == [
        "repair_order.created",
        "repair_order.updated",
        "repair_order.status_changed",
        "repair_order.updated",
    ]
    assert response.headers["X-Total-Count"] == "4"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert all(
        event["actor_id"] == accounts["employee"]
        and event["resource_id"] == order["id"]
        and event["succeeded"]
        for event in events
    )
    assert all(
        datetime.fromisoformat(event["occurred_at"]).utcoffset() == timedelta(0)
        for event in events
    )
    assert events[1]["details"]["changed_fields"] == [
        "expected_completion_date",
        "internal_notes",
        "work_description",
    ]
    assert events[1]["details"]["previous_expected_completion_date"] is None
    assert events[1]["details"]["new_expected_completion_date"] == "2026-12-01"
    assert events[2]["details"]["previous_status"] == "accepted"
    assert events[2]["details"]["new_status"] == "in_progress"
    assert events[3]["details"]["previous_expected_completion_date"] == "2026-12-01"
    assert events[3]["details"]["new_expected_completion_date"] is None
    assert "Private repair description" not in response.text
    assert "Revised private description" not in response.text
    assert "Private internal note" not in response.text
    assert "Revised private note" not in response.text


def test_history_contains_related_positions_documents_and_estimates_only(history_order):
    client, order, path = history_order
    item_path = f"/api/v1/repairs/{order['id']}/items"
    payload = {
        "kind": "service",
        "description": "Private line description",
        "quantity": "1",
        "unit_price": "20.00",
    }
    item = client.post(item_path, json=payload).json()
    assert (
        client.patch(f"{item_path}/{item['id']}", json={"quantity": "2"}).status_code
        == 200
    )
    document = client.post(
        f"/api/v1/repair-orders/{order['id']}/documents?filename=private-file.pdf",
        content=b"private document bytes",
    ).json()
    estimate_path = f"/api/v1/repairs/{order['id']}/estimates"
    quote = client.post(estimate_path, json={"items": [payload]}).json()
    issued = client.patch(
        f"{estimate_path}/{quote['id']}/status", json={"status": "issued"}
    ).json()
    assert (
        client.post(
            f"{estimate_path}/{quote['id']}/approval",
            json={"approved_at": issued["issued_at"], "approval_method": "email"},
        ).status_code
        == 200
    )
    other = client.post(
        "/api/v1/repairs",
        json={
            "customer_id": order["customer_id"],
            "instrument_id": order["instrument_id"],
            "work_description": "Another repair",
        },
    ).json()
    assert (
        client.post(f"/api/v1/repairs/{other['id']}/items", json=payload).status_code
        == 201
    )
    assert sign_in(client, "admin").status_code == 200
    response = client.get(path)
    assert response.status_code == 200, response.text
    events = response.json()
    assert [event["action"] for event in events] == [
        "repair_order.created",
        "repair_item.created",
        "repair_item.updated",
        "repair_document.created",
        "repair_estimate.created",
        "repair_estimate.status_changed",
        "repair_estimate.approved",
    ]
    assert events[2]["details"]["changed_fields"] == ["quantity"]
    assert events[3]["resource_id"] == document["id"]
    assert all(event["resource_id"] == quote["id"] for event in events[4:])
    assert "Private line description" not in response.text
    assert "private-file.pdf" not in response.text
    assert "private document bytes" not in response.text


@pytest.mark.parametrize(
    "offset,limit,indices",
    [(0, 1, [0]), (1, 2, [1, 2]), (2, 1, [2]), (3, 200, []), (999, 100, [])],
)
def test_history_pages_have_stable_timestamp_and_id_order(
    history_order, db_connection, offset, limit, indices
):
    client, order, path = history_order
    for archived in [True, False]:
        assert (
            client.patch(
                f"/api/v1/repair-orders/{order['id']}/archive",
                json={"is_archived": archived},
            ).status_code
            == 200
        )
    ids = list(
        db_connection.scalars(
            text(
                "SELECT id FROM audit_event WHERE resource_type='repair_order' AND resource_id=:id ORDER BY id"
            ),
            {"id": order["id"]},
        )
    )
    assert len(ids) == 3
    db_connection.execute(
        text("UPDATE audit_event SET occurred_at=:when WHERE id=ANY(:ids)"),
        {"when": datetime(2026, 1, 1, tzinfo=UTC), "ids": ids},
    )
    assert sign_in(client, "admin").status_code == 200
    response = client.get(path, params={"offset": offset, "limit": limit})
    assert response.status_code == 200
    assert [event["id"] for event in response.json()] == [
        ids[index] for index in indices
    ]
    assert response.headers["X-Total-Count"] == "3"


def test_no_ops_failed_changes_and_history_reads_do_not_add_repair_events(
    history_order, db_connection
):
    client, order, path = history_order
    assert client.patch(f"/api/v1/repairs/{order['id']}", json={}).status_code == 200
    assert (
        client.patch(
            f"/api/v1/repairs/{order['id']}/status", json={"status": "accepted"}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/repairs/{order['id']}/status", json={"status": "completed"}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/repairs/{order['id']}", json={"work_description": " "}
        ).status_code
        == 422
    )
    assert sign_in(client, "admin").status_code == 200
    before = client.get(path)
    assert before.status_code == 200
    assert len(before.json()) == 1
    assert client.get(path).json() == before.json()
    assert (
        db_connection.scalar(
            text("SELECT count(*) FROM audit_event WHERE action='audit.read'")
        )
        == 2
    )


def test_history_rolls_back_with_business_change(history_order, monkeypatch):
    client, order, path = history_order
    original = repair_service.record_event

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Simulated audit failure")

    monkeypatch.setattr(repair_service, "record_event", fail)
    with pytest.raises(RuntimeError, match="Simulated audit failure"):
        client.patch(
            f"/api/v1/repairs/{order['id']}",
            json={"expected_completion_date": "2026-12-01"},
        )
    assert sign_in(client, "admin").status_code == 200
    assert [event["action"] for event in client.get(path).json()] == [
        "repair_order.created"
    ]
    assert (
        client.get(f"/api/v1/repairs/{order['id']}").json()["expected_completion_date"]
        is None
    )


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 403), ("admin", 404)]
)
def test_history_requires_current_administrator(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        assert sign_in(client, role).status_code == 200
    assert client.get("/api/v1/repairs/999999/history").status_code == expected


def test_history_preserves_unknown_actors_and_deactivated_user_ids(
    history_order, db_connection, accounts
):
    client, order, path = history_order
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        record_event(
            session,
            AuditAction.REPAIR_ORDER_UPDATED,
            AuditResource.REPAIR_ORDER,
            order["id"],
        )
        identity = authenticate_user("admin@example.com", PASSWORD, session)
        assert identity is not None
        set_user_active(accounts["employee"], False, session, actor=identity)
    assert sign_in(client, "admin").status_code == 200
    response = client.get(path)
    assert response.status_code == 200
    assert [event["actor_id"] for event in response.json()] == [
        accounts["employee"],
        None,
    ]


def test_history_does_not_expose_security_events_or_invent_expired_history(
    history_order, db_connection
):
    client, order, path = history_order
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        session.add(
            AuditEvent(
                action="auth.login",
                resource_type="repair_order",
                resource_id=order["id"],
                actor_id=None,
                occurred_at=datetime.now(UTC),
                succeeded=False,
            )
        )
        session.commit()
    assert sign_in(client, "admin").status_code == 200
    assert [event["action"] for event in client.get(path).json()] == [
        "repair_order.created"
    ]
    db_connection.execute(
        text(
            "UPDATE audit_event SET occurred_at=:when WHERE resource_type='repair_order' AND resource_id=:id"
        ),
        {"when": datetime.now(UTC) - timedelta(days=31), "id": order["id"]},
    )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert purge_expired_events(session, 30) == 2
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["X-Total-Count"] == "0"
    assert client.get(f"/api/v1/repairs/{order['id']}").status_code == 200


def test_history_survives_archive_and_has_no_mutation_api(history_order):
    client, order, path = history_order
    assert (
        client.patch(
            f"/api/v1/repair-orders/{order['id']}/archive", json={"is_archived": True}
        ).status_code
        == 200
    )
    assert sign_in(client, "admin").status_code == 200
    assert [event["action"] for event in client.get(path).json()] == [
        "repair_order.created",
        "repair_order.archived",
    ]
    for method in [client.post, client.patch, client.delete]:
        assert method(path).status_code == 405


def test_legacy_child_events_resolve_without_parent_metadata(
    history_order, db_connection
):
    client, order, path = history_order
    document = client.post(
        f"/api/v1/repair-orders/{order['id']}/documents?filename=legacy.pdf",
        content=b"legacy bytes",
    ).json()
    db_connection.execute(
        text(
            "UPDATE audit_event SET details='{}'::json WHERE resource_type='repair_document' AND resource_id=:id"
        ),
        {"id": document["id"]},
    )
    assert sign_in(client, "admin").status_code == 200
    assert [event["action"] for event in client.get(path).json()] == [
        "repair_order.created",
        "repair_document.created",
    ]
