from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, select

from atelier_api.audit.models import AuditAction, AuditEvent
from atelier_api.photos.models import (
    MAX_PHOTO_BYTES,
    MAX_REQUEST_BYTES,
    InstrumentPhoto,
)
from atelier_api.photos.service import cleanup_abandoned_uploads
from atelier_api.photos.storage import get_storage
from tests.integration.auth_helpers import sign_in
from tests.photos.helpers import FakeStorage, image_bytes

pytestmark = pytest.mark.integration


@pytest.fixture
def photo_setup(auth_factory):
    storage = FakeStorage()
    client = auth_factory()
    client.app.dependency_overrides[get_storage] = lambda: storage
    sign_in(client)
    instrument = client.post("/api/v1/instruments", json={"type": "violin"}).json()
    return client, storage, instrument


def upload(
    client,
    instrument_id,
    *,
    count=1,
    format="PNG",
    mime="image/png",
    data=None,
    filename="photo.png",
):
    return client.post(
        f"/api/v1/instruments/{instrument_id}/photos",
        files=[
            (
                "files",
                (filename, data if data is not None else image_bytes(format), mime),
            )
            for _ in range(count)
        ],
    )


def photos(db_connection):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        return session.exec(select(InstrumentPhoto).order_by(InstrumentPhoto.id)).all()


def photo_events(db_connection):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        return session.exec(
            select(AuditEvent)
            .where(AuditEvent.resource_type == "instrument_photo")
            .order_by(AuditEvent.id)
        ).all()


@pytest.mark.parametrize(
    "format,mime",
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
@pytest.mark.e2e
def test_photo_upload_and_private_retrieval(
    photo_setup, db_connection, accounts, format, mime
):
    client, storage, instrument = photo_setup
    response = upload(
        client,
        instrument["id"],
        format=format,
        mime="application/octet-stream",
        filename="../../photo.exe",
    )
    assert response.status_code == 201, response.text
    (photo,) = response.json()
    assert photo["instrument_id"] == instrument["id"]
    assert photo["uploaded_by_user_id"] == accounts["employee"]
    assert photo["content_type"] == mime
    assert photo["original_filename"] == "photo.exe"
    assert datetime.fromisoformat(photo["uploaded_at"]).utcoffset() == timedelta(0)
    assert "storage_key" not in photo
    assert "bucket" not in response.text
    (stored,) = photos(db_connection)
    assert storage.exists(stored.storage_key)
    assert stored.storage_key.startswith("instruments/")
    assert UUID(stored.storage_key.split("/")[1]).version == 4
    assert UUID(stored.storage_key.split("/")[2].split(".")[0]).version == 4
    assert "photo" not in stored.storage_key
    base = f"/api/v1/instruments/{instrument['id']}/photos"
    listing = client.get(base)
    assert listing.json() == [photo]
    assert listing.headers["x-total-count"] == "1"
    assert listing.headers["cache-control"] == "private, no-store"
    assert client.get(f"{base}/{photo['id']}").json() == photo
    for suffix, disposition in [("content", "inline"), ("download", "attachment")]:
        result = client.get(f"{base}/{photo['id']}/{suffix}")
        assert result.status_code == 200
        assert result.headers["content-type"] == mime
        assert result.headers["content-disposition"].startswith(disposition)
        assert not result.headers["content-disposition"].endswith(".exe")
        assert result.headers["x-content-type-options"] == "nosniff"
        assert result.headers["cache-control"] == "private, no-store"
        assert result.content == storage.objects[stored.storage_key]
    assert all(stream.closed for stream in storage.closed_streams)
    (event,) = photo_events(db_connection)
    assert event.action == AuditAction.PHOTO_UPLOADED
    assert event.actor_id == accounts["employee"]
    assert event.resource_id == photo["id"]
    assert event.details == {"instrument_id": instrument["id"]}


def test_multiple_images_pagination_and_unique_keys(photo_setup):
    client, storage, instrument = photo_setup
    response = upload(client, instrument["id"], count=10)
    assert response.status_code == 201
    assert len(storage.objects) == 10
    base = f"/api/v1/instruments/{instrument['id']}/photos"
    page = client.get(base, params={"offset": 9, "limit": 1})
    assert page.json() == response.json()[9:]
    assert page.headers["x-total-count"] == "10"
    assert client.get(base, params={"offset": 10}).json() == []
    for params in [{"offset": -1}, {"limit": 0}, {"limit": 201}]:
        assert client.get(base, params=params).status_code == 422


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"count": 11}, 413),
        ({"data": b"x" * (MAX_PHOTO_BYTES + 1)}, 413),
        ({"data": b"invalid"}, 415),
        ({"format": "GIF"}, 415),
        ({"data": image_bytes("JPEG")[:-20]}, 422),
        ({"filename": ".."}, 422),
    ],
)
def test_rejected_uploads_have_no_objects_or_metadata(
    photo_setup, db_connection, changes, status
):
    client, storage, instrument = photo_setup
    response = upload(client, instrument["id"], **changes)
    assert response.status_code == status, response.text
    assert storage.objects == {}
    assert photos(db_connection) == []
    assert photo_events(db_connection) == []


def test_bad_multi_file_batch_uploads_nothing(photo_setup, db_connection):
    client, storage, instrument = photo_setup
    response = client.post(
        f"/api/v1/instruments/{instrument['id']}/photos",
        files=[
            ("files", ("good.png", image_bytes(), "image/png")),
            ("files", ("bad.png", b"bad", "image/png")),
        ],
    )
    assert response.status_code == 415
    assert not storage.uploads
    assert photos(db_connection) == []


def test_missing_instrument_checked_before_upload(photo_setup):
    client, storage, _ = photo_setup
    assert upload(client, 999999).status_code == 404
    assert client.get("/api/v1/instruments/999999/photos").status_code == 404
    assert not storage.uploads


@pytest.mark.parametrize("suffix", ["", "/1", "/1/content", "/1/download"])
@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_photo_access_rules(auth_factory, role, expected, suffix):
    client = auth_factory(customer_portal_auth_enabled=True)
    storage = FakeStorage()
    client.app.dependency_overrides[get_storage] = lambda: storage
    if role:
        sign_in(client, role)
    assert (
        client.get(f"/api/v1/instruments/999999/photos{suffix}").status_code == expected
    )
    assert not storage.downloads


@pytest.mark.parametrize(
    "method,role,expected",
    [
        ("POST", None, 401),
        ("POST", "customer", 403),
        ("DELETE", None, 401),
        ("DELETE", "customer", 403),
        ("DELETE", "employee", 403),
    ],
)
def test_photo_writes_enforce_roles(auth_factory, method, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    storage = FakeStorage()
    client.app.dependency_overrides[get_storage] = lambda: storage
    if role:
        sign_in(client, role)
    path = "/api/v1/instruments/999999/photos" + ("/1" if method == "DELETE" else "")
    assert client.request(method, path).status_code == expected
    assert not storage.uploads
    assert not storage.deletes


def test_cross_instrument_access_and_missing_photo(photo_setup):
    client, storage, first = photo_setup
    photo = upload(client, first["id"]).json()[0]
    second = client.post("/api/v1/instruments", json={"type": "bow"}).json()
    for suffix in ["", "/content", "/download"]:
        assert (
            client.get(
                f"/api/v1/instruments/{second['id']}/photos/{photo['id']}{suffix}"
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/v1/instruments/{first['id']}/photos/999999{suffix}"
            ).status_code
            == 404
        )
    sign_in(client, "admin")
    assert (
        client.delete(
            f"/api/v1/instruments/{second['id']}/photos/{photo['id']}"
        ).status_code
        == 404
    )
    assert not storage.downloads


@pytest.mark.e2e
def test_admin_soft_deletion_is_idempotent_and_preserves_evidence(
    photo_setup, db_connection, accounts
):
    client, storage, instrument = photo_setup
    photo = upload(client, instrument["id"]).json()[0]
    path = f"/api/v1/instruments/{instrument['id']}/photos/{photo['id']}"
    assert client.delete(path).status_code == 403
    sign_in(client, "admin")
    deleted = client.delete(path)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert deleted.json()["deletion_requested_by_user_id"] == accounts["admin"]
    assert client.delete(path).json() == deleted.json()
    assert client.get(path.rsplit("/", 1)[0]).json() == []
    for suffix in ["", "/content", "/download"]:
        assert client.get(path + suffix).status_code == 404
    assert len(storage.objects) == 1
    assert storage.deletes == []
    events = photo_events(db_connection)
    assert [event.action for event in events] == [
        AuditAction.PHOTO_UPLOADED,
        AuditAction.PHOTO_DELETION_REQUESTED,
    ]
    assert events[-1].actor_id == accounts["admin"]
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert cleanup_abandoned_uploads(session, storage) == 0
    assert len(storage.objects) == 1
    assert client.delete(f"/api/v1/instruments/{instrument['id']}").status_code == 409


@pytest.mark.parametrize("fail_number", [1, 2])
def test_failed_upload_batch_is_compensated(photo_setup, db_connection, fail_number):
    client, storage, instrument = photo_setup
    storage.fail_upload_number = fail_number
    result = upload(client, instrument["id"], count=2)
    assert result.status_code == 503
    assert "infrastructure" not in result.text
    assert not storage.objects
    assert photos(db_connection) == []
    assert photo_events(db_connection) == []


def test_failed_cleanup_leaves_durable_intents_for_retry(photo_setup, db_connection):
    client, storage, instrument = photo_setup
    storage.fail_upload_number = 2
    storage.fail_delete = True
    assert upload(client, instrument["id"], count=2).status_code == 503
    pending = photos(db_connection)
    assert len(pending) == 2
    assert all(photo.status == "pending" for photo in pending)
    assert {photo.storage_key for photo in pending} == set(storage.objects)
    assert client.get(f"/api/v1/instruments/{instrument['id']}/photos").json() == []
    storage.fail_delete = False
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert cleanup_abandoned_uploads(session, storage) == 0
        for photo in session.exec(select(InstrumentPhoto)).all():
            photo.uploaded_at = datetime.now(UTC) - timedelta(days=2)
            session.add(photo)
        session.commit()
        assert cleanup_abandoned_uploads(session, storage) == 2
    assert not storage.objects
    assert not photos(db_connection)


def test_database_audit_failure_rolls_back_metadata_and_cleans_storage(
    photo_setup, db_connection, monkeypatch
):
    client, storage, instrument = photo_setup

    def fail(*args, **kwargs):
        raise SQLAlchemyError("Private database error")

    monkeypatch.setattr("atelier_api.photos.service.record_event", fail)
    response = upload(client, instrument["id"], count=2)
    assert response.status_code == 503
    assert "Private" not in response.text
    assert not storage.objects
    assert not photos(db_connection)
    assert not photo_events(db_connection)


def test_deletion_and_audit_are_atomic(photo_setup, db_connection, monkeypatch):
    client, storage, instrument = photo_setup
    photo = upload(client, instrument["id"]).json()[0]
    sign_in(client, "admin")

    def fail(*args, **kwargs):
        raise SQLAlchemyError("Private database error")

    monkeypatch.setattr("atelier_api.photos.router.record_event", fail)
    path = f"/api/v1/instruments/{instrument['id']}/photos/{photo['id']}"
    assert client.delete(path).status_code == 503
    assert client.get(path).json()["status"] == "ready"
    assert len(photo_events(db_connection)) == 1
    assert len(storage.objects) == 1


def test_unavailable_objects_are_safe(photo_setup):
    client, storage, instrument = photo_setup
    photo = upload(client, instrument["id"]).json()[0]
    path = f"/api/v1/instruments/{instrument['id']}/photos/{photo['id']}"
    storage.fail_download = True
    response = client.get(path + "/content")
    assert response.status_code == 503
    assert "infrastructure" not in response.text
    storage.fail_download = False
    storage.objects.clear()
    assert client.get(path + "/download").status_code == 404
    assert client.get(path).status_code == 200


def test_photos_survive_customer_and_repair_archiving(photo_setup):
    client, storage, instrument = photo_setup
    customer = client.post(
        "/api/v1/customers", json={"first_name": "Photo", "last_name": "Owner"}
    ).json()
    client.patch(
        f"/api/v1/instruments/{instrument['id']}",
        json={"customer_id": customer["id"], "ownership": "customer"},
    )
    photo = upload(client, instrument["id"]).json()[0]
    assert (
        client.patch(
            f"/api/v1/customers/{customer['id']}/archive", json={"is_archived": True}
        ).status_code
        == 200
    )
    path = f"/api/v1/instruments/{instrument['id']}/photos/{photo['id']}/content"
    assert client.get(path).status_code == 200
    assert len(storage.objects) == 1


def test_missing_storage_does_not_break_metadata_or_startup(auth_factory):
    client = auth_factory()
    sign_in(client)
    instrument = client.post("/api/v1/instruments", json={"type": "viola"}).json()
    assert client.get(f"/api/v1/instruments/{instrument['id']}/photos").json() == []
    assert upload(client, instrument["id"]).status_code == 503


def test_photo_database_constraints(photo_setup, db_connection):
    client, _, instrument = photo_setup
    photo = upload(client, instrument["id"]).json()[0]
    for assignment in [
        "file_size_bytes = 0",
        "file_size_bytes = 10000001",
        "content_type = 'text/html'",
        "status = 'invalid'",
        "status = 'deleted'",
        "instrument_id = -1",
        "uploaded_by_user_id = -1",
    ]:
        with Session(
            bind=db_connection, join_transaction_mode="create_savepoint"
        ) as session:
            with pytest.raises(IntegrityError):
                session.execute(
                    text(f"UPDATE instrument_photo SET {assignment} WHERE id = :id"),
                    {"id": photo["id"]},
                )
            session.rollback()
    columns = inspect(db_connection).get_columns("instrument_photo")
    assert not any(str(column["type"]) == "BYTEA" for column in columns)
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(InstrumentPhoto, photo["id"])
        assert stored is not None
        clone = InstrumentPhoto(
            instrument_id=instrument["id"],
            storage_key=stored.storage_key,
            storage_namespace=stored.storage_namespace,
            original_filename="other.png",
            content_type="image/png",
            file_size_bytes=1,
        )
        session.add(clone)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_request_size_is_rejected_before_parsing(photo_setup):
    client, storage, instrument = photo_setup
    response = client.post(
        f"/api/v1/instruments/{instrument['id']}/photos",
        content=b"",
        headers={
            "content-type": "multipart/form-data; boundary=demo",
            "content-length": str(MAX_REQUEST_BYTES + 1),
        },
    )
    assert response.status_code == 413
    assert not storage.uploads


def test_intent_failure_never_touches_storage(photo_setup, db_connection, monkeypatch):
    client, storage, instrument = photo_setup
    original = Session.flush

    def fail_photo_insert(session, *args, **kwargs):
        if any(isinstance(item, InstrumentPhoto) for item in session.new):
            raise SQLAlchemyError("Sensitive insert failure")
        return original(session, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", fail_photo_insert)
    assert upload(client, instrument["id"]).status_code == 503
    assert storage.uploads == []
    assert photos(db_connection) == []


def test_final_commit_failure_is_compensated(photo_setup, db_connection, monkeypatch):
    client, storage, instrument = photo_setup
    original = Session.commit
    failed = False

    def fail_ready_commit(session):
        nonlocal failed
        if not failed and any(
            isinstance(item, InstrumentPhoto) and item.status == "ready"
            for item in session.identity_map.values()
        ):
            failed = True
            raise SQLAlchemyError("Sensitive commit failure")
        return original(session)

    monkeypatch.setattr(Session, "commit", fail_ready_commit)
    assert upload(client, instrument["id"], count=2).status_code == 503
    assert failed
    assert not storage.objects
    assert photos(db_connection) == []
    assert photo_events(db_connection) == []


def test_conditional_collision_never_deletes_existing_object(
    photo_setup, db_connection, monkeypatch
):
    from atelier_api.photos.storage import ObjectConflict

    client, storage, instrument = photo_setup

    def conflict(key, source, size, content_type):
        storage.objects[key] = b"Existing evidence"
        raise ObjectConflict

    monkeypatch.setattr(storage, "upload", conflict)
    assert upload(client, instrument["id"]).status_code == 503
    assert list(storage.objects.values()) == [b"Existing evidence"]
    assert storage.deletes == []
    assert photos(db_connection) == []


def test_staff_upload_requires_existing_csrf_protection(photo_setup):
    client, storage, instrument = photo_setup
    response = client.post(
        f"/api/v1/instruments/{instrument['id']}/photos",
        files={"files": ("photo.png", image_bytes(), "image/png")},
        headers={"Origin": "https://attacker.example", "X-CSRF-Protection": "1"},
    )
    assert response.status_code == 403
    assert not storage.uploads


def test_uploader_deactivation_preserves_photo_attribution(
    photo_setup, db_connection, accounts
):
    client, storage, instrument = photo_setup
    photo = upload(client, instrument["id"]).json()[0]
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        session.execute(
            text("UPDATE app_user SET is_active = false WHERE id = :id"),
            {"id": accounts["employee"]},
        )
        session.commit()
    sign_in(client, "admin")
    assert (
        client.get(
            f"/api/v1/instruments/{instrument['id']}/photos/{photo['id']}"
        ).json()["uploaded_by_user_id"]
        == accounts["employee"]
    )
    assert len(storage.objects) == 1


def test_storage_location_change_does_not_lose_pending_tracking(
    photo_setup, db_connection
):
    client, storage, instrument = photo_setup
    storage.fail_upload_number = 1
    storage.fail_delete = True
    assert upload(client, instrument["id"]).status_code == 503
    (pending,) = photos(db_connection)
    original_namespace = storage.namespace
    storage.namespace = "different-bucket"
    storage.fail_delete = False
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        row = session.get(InstrumentPhoto, pending.id)
        assert row is not None
        row.uploaded_at = datetime.now(UTC) - timedelta(days=2)
        session.add(row)
        session.commit()
        assert cleanup_abandoned_uploads(session, storage) == 0
    assert len(photos(db_connection)) == 1
    assert len(storage.objects) == 1
    storage.namespace = original_namespace
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert cleanup_abandoned_uploads(session, storage) == 1
    assert not storage.objects


def test_wrong_storage_location_cannot_serve_other_bucket_contents(photo_setup):
    client, storage, instrument = photo_setup
    photo = upload(client, instrument["id"]).json()[0]
    storage.namespace = "different-bucket"
    response = client.get(
        f"/api/v1/instruments/{instrument['id']}/photos/{photo['id']}/content"
    )
    assert response.status_code == 503
    assert storage.downloads == []
