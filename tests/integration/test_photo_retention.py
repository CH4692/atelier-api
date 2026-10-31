from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from atelier_api.audit.models import AuditEvent
from atelier_api.photos.models import InstrumentPhoto
from atelier_api.photos.storage import StorageError, get_storage
from tests.integration.auth_helpers import sign_in
from tests.photos.helpers import FakeStorage, image_bytes

pytestmark = pytest.mark.integration


@pytest.fixture
def retention_photo(auth_factory):
    client = auth_factory()
    storage = FakeStorage()
    client.app.dependency_overrides[get_storage] = lambda: storage
    sign_in(client, "admin")
    instrument = client.post("/api/v1/instruments", json={"type": "violin"}).json()
    photo = client.post(
        f"/api/v1/instruments/{instrument['id']}/photos",
        files={"files": ("photo.png", image_bytes(), "image/png")},
    ).json()[0]
    path = f"/api/v1/instruments/{instrument['id']}/photos/{photo['id']}"
    return client, storage, path, photo


@pytest.mark.e2e
def test_restore_makes_deleted_photo_visible_and_audits(
    retention_photo, db_connection, accounts
):
    client, storage, path, photo = retention_photo
    first = client.delete(path)
    assert first.status_code == 200
    assert client.delete(path).json() == first.json()
    assert client.get(path).status_code == 404
    restored = client.post(path + "/restore")
    assert restored.status_code == 200
    assert restored.json()["status"] == "ready"
    assert restored.json()["deletion_requested_at"] is None
    assert client.get(path + "/content").status_code == 200
    assert len(storage.objects) == 1
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        events = session.exec(
            select(AuditEvent).where(AuditEvent.action == "instrument_photo.restored")
        ).all()
        assert len(events) == 1
        assert events[0].actor_id == accounts["admin"]
        assert events[0].resource_id == photo["id"]


@pytest.mark.parametrize(
    "suffix,method,payload",
    [
        ("/restore", "POST", {}),
        ("/retention-hold", "POST", {"reason": "Evidence"}),
        ("/retention-hold", "DELETE", {}),
        ("/retention", "GET", {}),
        ("/purge-approval", "POST", {"confirm_no_retention_requirements": True}),
    ],
)
@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("employee", 403), ("customer", 403)]
)
def test_retention_endpoints_are_admin_only(
    auth_factory, suffix, method, payload, role, expected
):
    client = auth_factory(customer_portal_auth_enabled=True)
    client.app.dependency_overrides[get_storage] = lambda: FakeStorage()
    if role:
        sign_in(client, role)
    assert (
        client.request(
            method, "/api/v1/instruments/1/photos/1" + suffix, json=payload
        ).status_code
        == expected
    )


def test_restore_rejects_active_missing_wrong_instrument_and_csrf(retention_photo):
    client, _, path, _ = retention_photo
    assert client.post(path + "/restore").status_code == 409
    assert (
        client.post("/api/v1/instruments/999999/photos/999999/restore").status_code
        == 404
    )
    client.delete(path)
    parts = path.split("/")
    parts[4] = "999999"
    assert client.post("/".join(parts) + "/restore").status_code == 404
    assert (
        client.post(
            path + "/restore", headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )


def test_missing_and_unavailable_storage_never_restores(retention_photo, monkeypatch):
    client, storage, path, _ = retention_photo
    client.delete(path)
    storage.objects.clear()
    assert client.post(path + "/restore").status_code == 409

    def fail(key):
        raise StorageError

    monkeypatch.setattr(storage, "exists", fail)
    assert client.post(path + "/restore").status_code == 503
    assert client.get(path).status_code == 404


def test_expired_and_purging_photos_cannot_restore(retention_photo, db_connection):
    client, _, path, photo = retention_photo
    client.delete(path)
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        row = session.get(InstrumentPhoto, photo["id"])
        row.deletion_requested_at = datetime.now(UTC) - timedelta(days=31)
        session.add(row)
        session.commit()
    assert client.post(path + "/restore").status_code == 409
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        row = session.get(InstrumentPhoto, photo["id"])
        row.status = "purging"
        row.purge_approved_at = datetime.now(UTC)
        session.add(row)
        session.commit()
    assert client.post(path + "/restore").status_code == 409
    assert client.delete(path).status_code == 409
    assert (
        client.post(path + "/retention-hold", json={"reason": "Late hold"}).status_code
        == 409
    )
    assert client.get(path + "/content").status_code == 404


@pytest.mark.e2e
def test_holds_require_explicit_release_and_approval(
    retention_photo, db_connection, accounts
):
    client, _, path, photo = retention_photo
    assert (
        client.post(path + "/retention-hold", json={"reason": "  "}).status_code == 422
    )
    hold = client.post(
        path + "/retention-hold", json={"reason": "  Contract evidence  "}
    )
    assert hold.status_code == 200
    assert hold.json()["retention_hold_reason"] == "Contract evidence"
    assert hold.json()["retention_hold_by_user_id"] == accounts["admin"]
    assert (
        client.post(
            path + "/retention-hold", json={"reason": "Contract evidence"}
        ).json()
        == hold.json()
    )
    assert (
        client.post(path + "/retention-hold", json={"reason": "Other"}).status_code
        == 409
    )
    client.delete(path)
    assert (
        client.get(path + "/retention").json()["retention_hold_reason"]
        == "Contract evidence"
    )
    assert (
        client.post(
            path + "/purge-approval", json={"confirm_no_retention_requirements": True}
        ).status_code
        == 409
    )
    assert client.delete(path + "/retention-hold").status_code == 200
    assert client.delete(path + "/retention-hold").status_code == 200
    assert (
        client.post(
            path + "/purge-approval", json={"confirm_no_retention_requirements": False}
        ).status_code
        == 422
    )
    approved = client.post(
        path + "/purge-approval", json={"confirm_no_retention_requirements": True}
    )
    assert approved.status_code == 200
    assert approved.json()["purge_approved_at"]
    assert (
        client.post(
            path + "/purge-approval", json={"confirm_no_retention_requirements": True}
        ).json()
        == approved.json()
    )
    assert client.post(path + "/restore").status_code == 200
    assert client.get(path + "/retention").json()["purge_approved_at"] is None
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        events = session.exec(
            select(AuditEvent).where(
                AuditEvent.resource_id == photo["id"],
                AuditEvent.resource_type == "instrument_photo",
            )
        ).all()
        actions = [event.action for event in events]
        assert actions.count("instrument_photo.hold_created") == 1
        assert actions.count("instrument_photo.hold_released") == 1
        assert actions.count("instrument_photo.purge_approved") == 1
        assert all("Contract" not in str(event.details) for event in events)


def test_restore_rejects_employee_before_storage_configuration(auth_factory):
    client = auth_factory()
    sign_in(client, "employee")
    response = client.post("/api/v1/instruments/1/photos/1/restore")
    assert response.status_code == 403
