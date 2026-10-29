"""Verify persisted audit facts, privacy, authorization and transactional behavior."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, select

from atelier_api.audit.models import AuditAction, AuditEvent, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import purge_expired_events, record_event
from atelier_api.customers import router as customer_routes
from atelier_api.customers.models import Customer
from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import InstrumentType
from atelier_api.users.authentication import authenticate_user
from atelier_api.users.models import User
from atelier_api.users.roles import UserRole
from atelier_api.users.schemas import UserCreate
from atelier_api.users.service import (
    create_user,
    delete_user,
    set_customer_association,
    set_user_active,
    set_user_role,
)
from tests.integration.auth_helpers import PASSWORD, sign_in

pytestmark = pytest.mark.integration


def events(connection):
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        return session.exec(select(AuditEvent).order_by(AuditEvent.id)).all()


def test_audit_migration_has_independent_ids_indexes_and_timezone(postgres_engine):
    inspector = inspect(postgres_engine)
    assert inspector.get_pk_constraint("audit_event")["constrained_columns"] == ["id"]
    columns = {
        column["name"]: column for column in inspector.get_columns("audit_event")
    }
    assert columns["occurred_at"]["type"].timezone
    assert not inspector.get_foreign_keys("audit_event")
    assert {"actor_id", "action", "resource_type", "resource_id", "occurred_at"} <= {
        index["column_names"][0] for index in inspector.get_indexes("audit_event")
    }


@pytest.mark.parametrize(
    "path,resource,payload,changes",
    [
        (
            "customers",
            "customer",
            {
                "first_name": "Private",
                "last_name": "Name",
                "email": "private@example.com",
            },
            {"first_name": "Changed"},
        ),
        (
            "instruments",
            "instrument",
            {"type": "violin", "notes": "Private notes"},
            {"maker": "Changed"},
        ),
    ],
)
def test_business_operations_record_actor_resource_action_and_utc(
    auth_factory, db_connection, accounts, path, resource, payload, changes
):
    client = auth_factory()
    assert sign_in(client, "admin").status_code == 200
    created = client.post(f"/api/v1/{path}", json=payload)
    assert created.status_code == 201
    resource_id = created.json()["id"]
    assert (
        client.patch(f"/api/v1/{path}/{resource_id}", json=changes).status_code == 200
    )
    assert client.patch(f"/api/v1/{path}/{resource_id}", json={}).status_code == 200
    assert client.delete(f"/api/v1/{path}/{resource_id}").status_code == 204
    records = [
        event for event in events(db_connection) if event.resource_type == resource
    ]
    assert [event.action for event in records] == [
        f"{resource}.created",
        f"{resource}.updated",
        f"{resource}.deleted",
    ]
    assert len({event.id for event in records}) == 3
    for event in records:
        assert isinstance(event.id, int)
        assert event.actor_id == accounts["admin"]
        assert event.resource_id == resource_id
        assert event.succeeded is True
        assert event.occurred_at.utcoffset() == timedelta(0)
        assert event.details == {}
        assert "Private" not in event.model_dump_json()


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("employee", 403), ("customer", 403), ("admin", 200)]
)
def test_audit_access_requires_current_administrator(
    auth_factory, db_connection, accounts, role, expected
):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        assert sign_in(client, role).status_code == 200
    response = client.get("/api/v1/audit-events")
    assert response.status_code == expected
    assert response.headers["cache-control"] == "no-store"
    if expected == 403:
        event = events(db_connection)[-1]
        assert event.action == "audit.access_denied"
        assert event.actor_id == accounts[role]
        assert event.succeeded is False


def test_admin_can_filter_and_paginate_without_exposing_account_data(
    auth_factory, db_connection, accounts
):
    client = auth_factory()
    sign_in(client, "admin")
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        for resource_id in (9, 9, 10):
            record_event(
                session,
                AuditAction.CUSTOMER_CREATED,
                AuditResource.CUSTOMER,
                resource_id,
                actor_id=accounts["admin"],
            )
        session.commit()
    matching = [event for event in events(db_connection) if event.resource_id == 9]
    params = {
        "actor_id": accounts["admin"],
        "resource_type": "customer",
        "resource_id": 9,
        "action": "customer.created",
        "since": matching[0].occurred_at.isoformat(),
        "until": matching[1].occurred_at.isoformat(),
        "limit": 1,
    }
    first = client.get("/api/v1/audit-events", params=params)
    assert first.status_code == 200
    assert [event["id"] for event in first.json()] == [matching[1].id]
    params["before_id"] = matching[1].id
    second = client.get("/api/v1/audit-events", params=params)
    assert [event["id"] for event in second.json()] == [matching[0].id]
    for key in ("email", "first_name", "hashed_password", "token_hash"):
        assert key not in first.text
    for invalid in (
        {"since": "2026-01-01T00:00:00"},
        {"since": "2026-02-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"},
        {"limit": 201},
    ):
        assert client.get("/api/v1/audit-events", params=invalid).status_code == 422


def test_successful_audit_reads_record_actor_without_query_contents(
    auth_factory, db_connection, accounts
):
    client = auth_factory()
    sign_in(client, "admin")
    response = client.get("/api/v1/audit-events", params={"action": "audit.read"})
    assert response.status_code == 200
    assert response.json() == []
    event = events(db_connection)[-1]
    assert event.action == "audit.read"
    assert event.actor_id == accounts["admin"]
    assert event.resource_type == "audit"
    assert event.resource_id is None
    assert event.succeeded is True
    assert event.details == {}
    following = client.get("/api/v1/audit-events", params={"action": "audit.read"})
    assert [item["id"] for item in following.json()] == [event.id]


@pytest.mark.parametrize("role", ["admin", "employee", "customer"])
def test_audit_has_no_ordinary_write_api(auth_factory, db_connection, role):
    client = auth_factory(customer_portal_auth_enabled=True)
    sign_in(client, role)
    before = [event.model_dump() for event in events(db_connection)]
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for path in ("/api/v1/audit-events", "/api/v1/audit-events/1"):
            assert client.request(
                method, path, json={"action": "forged"}
            ).status_code in {404, 405}
    assert [event.model_dump() for event in events(db_connection)] == before


def test_authentication_records_facts_without_passwords_or_cookie_verifiers(
    auth_factory, db_connection, accounts
):
    client = auth_factory()
    assert sign_in(client, "admin").status_code == 200
    first = client.cookies.get("__Host-session")
    assert (
        sign_in(client, "admin", password="invalid-private-password").status_code == 401
    )
    assert sign_in(client, "admin").status_code == 200
    second = client.cookies.get("__Host-session")
    assert first != second
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set("__Host-session", second)
    assert client.get("/api/v1/auth/me").status_code == 401
    records = events(db_connection)
    assert [event.succeeded for event in records if event.action == "auth.login"] == [
        True,
        False,
        True,
    ]
    failed = next(
        event
        for event in records
        if event.action == "auth.login" and not event.succeeded
    )
    assert failed.actor_id is None and failed.resource_id is None
    assert failed.details == {}
    for action in ("auth.session_revoked", "auth.logout"):
        assert any(
            event.action == action and event.actor_id == accounts["admin"]
            for event in records
        )
    assert any(
        event.action == "auth.session_rejected" and not event.succeeded
        for event in records
    )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        password_hash = session.get(User, accounts["admin"]).hashed_password
    serialized = "".join(event.model_dump_json() for event in records)
    for secret in (
        PASSWORD,
        "invalid-private-password",
        password_hash,
        first,
        second,
        sha256(first.encode()).hexdigest(),
        sha256(second.encode()).hexdigest(),
        "admin@example.com",
    ):
        assert secret not in serialized


def test_throttled_login_is_a_failed_audit_event(auth_factory, db_connection):
    client = auth_factory(login_account_limit=1)
    assert sign_in(client).status_code == 200
    assert sign_in(client).status_code == 429
    event = events(db_connection)[-1]
    assert event.action == "auth.login_throttled"
    assert event.succeeded is False
    assert event.actor_id is None
    assert event.resource_id is None


def test_user_management_preserves_history_and_safe_change_details(
    db_connection, accounts
):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        actor = authenticate_user("admin@example.com", PASSWORD, session)
        customer = Customer(
            first_name="Private", last_name="Customer", email="associated@example.com"
        )
        session.add(customer)
        session.commit()
        session.refresh(customer)
        target = create_user(
            UserCreate(email="new@example.com", password=PASSWORD),
            session,
            actor=actor,
            role=UserRole.CUSTOMER,
        )
        set_customer_association(target.id, customer.id, session, actor=actor)
        set_user_active(target.id, False, session, actor=actor)
        set_user_active(target.id, True, session, actor=actor)
        set_user_role(target.id, UserRole.EMPLOYEE, session, actor=actor)
        set_customer_association(target.id, None, session, actor=actor)
        delete_user(target.id, session, actor=actor)
        assert session.get(User, target.id) is None
        records = session.exec(
            select(AuditEvent)
            .where(AuditEvent.resource_id == target.id)
            .order_by(AuditEvent.id)
        ).all()
        assert {event.action for event in records} >= {
            "user.created",
            "user.customer_association_changed",
            "user.activated",
            "user.deactivated",
            "user.role_changed",
            "user.sessions_revoked",
            "user.deleted",
        }
        assert all(event.actor_id == accounts["admin"] for event in records)
        association = next(
            event
            for event in records
            if event.action == "user.customer_association_changed"
        )
        assert association.details == {
            "previous_customer_id": None,
            "new_customer_id": customer.id,
        }
        role = next(event for event in records if event.action == "user.role_changed")
        assert role.details == {"previous_role": "customer", "new_role": "employee"}
        assert (
            next(
                event for event in records if event.action == "user.deactivated"
            ).details["new_role"]
            == "customer"
        )
        assert all(
            "new@example.com" not in event.model_dump_json() for event in records
        )


def test_business_and_event_roll_back_together(
    auth_factory, db_connection, monkeypatch
):
    client = auth_factory()
    sign_in(client, "admin")
    before_customers = db_connection.scalar(text("SELECT count(*) FROM customer"))
    before_events = len(events(db_connection))
    original = customer_routes.record_event

    def append_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Simulated failure after writing audit event")

    monkeypatch.setattr(customer_routes, "record_event", append_then_fail)
    with pytest.raises(RuntimeError, match="Simulated failure"):
        client.post(
            "/api/v1/customers",
            json={
                "first_name": "Rollback",
                "last_name": "Test",
                "email": "rollback@example.com",
            },
        )
    assert (
        db_connection.scalar(text("SELECT count(*) FROM customer")) == before_customers
    )
    assert len(events(db_connection)) == before_events


def test_retention_removes_only_expired_events_and_audits_cleanup(db_connection):
    now = datetime.now(UTC)
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        old = AuditEvent(
            action="customer.created",
            resource_type="customer",
            succeeded=True,
            occurred_at=now - timedelta(days=181),
        )
        recent = AuditEvent(
            action="customer.created",
            resource_type="customer",
            succeeded=True,
            occurred_at=now - timedelta(days=179),
        )
        session.add_all([old, recent])
        session.commit()
        with pytest.raises(ValueError):
            purge_expired_events(session, 0)
        assert purge_expired_events(session, 180) == 1
        remaining = session.exec(select(AuditEvent).order_by(AuditEvent.id)).all()
        assert [event.id for event in remaining[:-1]] == [recent.id]
        assert remaining[-1].action == "audit.retention"
        assert remaining[-1].details == {"removed_count": 1}


def test_audit_metadata_rejects_secrets_and_arbitrary_request_bodies():
    from pydantic import ValidationError

    for field in ("password", "password_hash", "token", "token_hash", "body", "email"):
        with pytest.raises(ValidationError):
            AuditDetails.model_validate({field: "private"})


def test_customer_deletion_audits_implicit_account_disassociation(
    auth_factory, db_connection, accounts
):
    client = auth_factory()
    sign_in(client, "employee")
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        account = session.get(User, accounts["customer"])
        customer_id = account.customer_id
        instrument = Instrument(type=InstrumentType.VIOLIN, customer_id=customer_id)
        session.add(instrument)
        session.commit()
        session.refresh(instrument)
        instrument_id = instrument.id
    assert client.delete(f"/api/v1/customers/{customer_id}").status_code == 204
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert session.get(User, accounts["customer"]).customer_id is None
    record = next(
        event
        for event in events(db_connection)
        if event.action == "user.customer_association_changed"
    )
    assert record.actor_id == accounts["employee"]
    assert record.resource_id == accounts["customer"]
    assert record.details == {
        "previous_customer_id": customer_id,
        "new_customer_id": None,
    }
    instrument_event = next(
        event for event in events(db_connection) if event.action == "instrument.updated"
    )
    assert instrument_event.resource_id == instrument_id
    assert instrument_event.actor_id == accounts["employee"]
    assert instrument_event.details == record.details


def test_failed_rotation_preserves_previous_session_and_audit_history(
    auth_factory, db_connection, monkeypatch
):
    from atelier_api.auth import service as auth_service
    from atelier_api.auth.models import UserSession

    client = auth_factory()
    sign_in(client, "admin")
    before = [event.model_dump() for event in events(db_connection)]
    original = auth_service.record_event

    def fail_after_login_event(session, action, *args, **kwargs):
        original(session, action, *args, **kwargs)
        if action == AuditAction.LOGIN:
            raise RuntimeError("Simulated login audit failure")

    monkeypatch.setattr(auth_service, "record_event", fail_after_login_event)
    with pytest.raises(RuntimeError, match="Simulated login audit failure"):
        sign_in(client, "admin")
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        record = session.exec(select(UserSession)).one()
        assert record.revoked_at is None
    assert [event.model_dump() for event in events(db_connection)] == before
    assert client.get("/api/v1/auth/me").status_code == 200


def test_bootstrap_and_deleted_actor_keep_historical_accountability(db_connection):
    from atelier_api.users.service import bootstrap_admin

    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        first = bootstrap_admin(
            UserCreate(email="first@example.com", password=PASSWORD), session
        )
        actor = authenticate_user(first.email, PASSWORD, session)
        second = create_user(
            UserCreate(email="second@example.com", password=PASSWORD),
            session,
            actor=actor,
            role=UserRole.ADMIN,
        )
        second_actor = authenticate_user(second.email, PASSWORD, session)
        set_user_active(first.id, False, session, actor=second_actor)
        delete_user(first.id, session, actor=second_actor)
        assert session.get(User, first.id) is None
        history = session.exec(select(AuditEvent).order_by(AuditEvent.id)).all()
        assert history[0].action == "user.bootstrapped"
        assert history[0].resource_id == first.id
        assert history[0].actor_id is None
        assert any(
            event.actor_id == first.id and event.resource_id == second.id
            for event in history
        )


def test_customer_portal_workshop_denial_is_a_security_event(
    auth_factory, db_connection, accounts
):
    client = auth_factory(customer_portal_auth_enabled=True)
    assert sign_in(client, "customer").status_code == 200
    assert client.get("/api/v1/customers").status_code == 403
    event = events(db_connection)[-1]
    assert event.action == "auth.workshop_access_denied"
    assert event.actor_id == accounts["customer"]
    assert event.succeeded is False
    assert event.details == {}
