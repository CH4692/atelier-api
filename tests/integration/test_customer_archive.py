"""Verify persisted archival without losing related instruments or accounts."""

import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from atelier_api.audit.models import AuditEvent
from atelier_api.customers import router as customer_routes
from atelier_api.customers.models import Customer
from atelier_api.users.models import User
from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration


def test_archive_restore_preserves_associations_and_search_counts(
    auth_factory, db_connection, accounts
):
    client = auth_factory(customer_portal_auth_enabled=True)
    sign_in(client, "employee")
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        user = session.get(User, accounts["customer"])
        customer_id, auth_version = user.customer_id, user.auth_version
        original = session.get(Customer, customer_id).model_dump()
    path = f"/api/v1/customers/{customer_id}"
    instrument = client.post(
        "/api/v1/instruments", json={"type": "violin", "customer_id": customer_id}
    ).json()
    response = client.patch(f"{path}/archive", json={"is_archived": True})
    assert response.status_code == 200
    assert response.json() == {**original, "is_archived": True}
    for params in ({}, {"q": original["email"]}):
        page = client.get("/api/v1/customers", params=params)
        assert page.json() == []
        assert page.headers["X-Total-Count"] == "0"
    included = client.get("/api/v1/customers", params={"include_archived": True})
    assert included.json() == [response.json()]
    assert included.headers["X-Total-Count"] == "1"
    assert client.get(path).json()["is_archived"] is True
    assert client.get(f"{path}/instruments").json() == [instrument]
    assert client.get(f"/api/v1/instruments/{instrument['id']}").json() == instrument
    assert (
        client.patch(f"{path}/archive", json={"is_archived": True}).status_code == 200
    )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        user = session.get(User, accounts["customer"])
        assert user.customer_id == customer_id and user.auth_version == auth_version
    restored = client.patch(f"{path}/archive", json={"is_archived": False})
    assert restored.json() == original
    assert client.get("/api/v1/customers").json() == [original]
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        events = session.exec(
            select(AuditEvent)
            .where(AuditEvent.action.in_(["customer.archived", "customer.restored"]))
            .order_by(AuditEvent.id)
        ).all()
        assert [event.action for event in events] == [
            "customer.archived",
            "customer.restored",
        ]
        assert all(
            event.actor_id == accounts["employee"] and event.resource_id == customer_id
            for event in events
        )


def test_archive_and_event_roll_back_together(auth_factory, db_connection, monkeypatch):
    client = auth_factory()
    sign_in(client, "employee")
    customer = client.get("/api/v1/customers").json()[0]
    before = db_connection.scalar(text("SELECT count(*) FROM audit_event"))
    original = customer_routes.record_event

    def append_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Simulated audit failure")

    monkeypatch.setattr(customer_routes, "record_event", append_then_fail)
    with pytest.raises(RuntimeError, match="Simulated audit failure"):
        client.patch(
            f"/api/v1/customers/{customer['id']}/archive", json={"is_archived": True}
        )
    assert client.get(f"/api/v1/customers/{customer['id']}").json() == customer
    assert db_connection.scalar(text("SELECT count(*) FROM audit_event")) == before


@pytest.mark.parametrize("role,expected", [(None, 401), ("customer", 403)])
def test_archive_requires_workshop_access(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        sign_in(client, role)
    assert (
        client.patch(
            "/api/v1/customers/1/archive", json={"is_archived": True}
        ).status_code
        == expected
    )


def test_permanent_deletion_remains_a_separate_operation(postgres_client):
    customer = postgres_client.post(
        "/api/v1/customers",
        json={"first_name": "Maria", "last_name": "Doe", "email": "maria@example.com"},
    ).json()
    path = f"/api/v1/customers/{customer['id']}"
    assert (
        postgres_client.patch(f"{path}/archive", json={"is_archived": True}).status_code
        == 200
    )
    assert postgres_client.get(path).status_code == 200
    assert postgres_client.delete(path).status_code == 204
    assert postgres_client.get(path).status_code == 404
