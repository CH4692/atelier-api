"""Verify reversible archival, default visibility and retained business history."""

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlmodel import Session, select

from atelier_api.audit.models import AuditEvent
from atelier_api.instruments.models import Instrument
from atelier_api.photos.storage import get_storage
from tests.integration.auth_helpers import sign_in
from tests.photos.helpers import FakeStorage, image_bytes

pytestmark = pytest.mark.integration


@pytest.fixture
def archived_instrument_setup(auth_factory):
    client = auth_factory(public_qr_base_url="https://records.example.test")
    assert sign_in(client, "employee").status_code == 200
    customer = client.post(
        "/api/v1/customers", json={"first_name": "Archive", "last_name": "Owner"}
    ).json()
    instrument = client.post(
        "/api/v1/instruments",
        json={
            "type": "violin",
            "customer_id": customer["id"],
            "identification_number": "ARCHIVE-1",
        },
    ).json()
    return client, customer, instrument, f"/api/v1/instruments/{instrument['id']}"


@pytest.mark.e2e
def test_archive_restore_and_default_list_visibility(archived_instrument_setup):
    client, customer, instrument, path = archived_instrument_setup
    assert instrument["is_archived"] is False
    archived = client.patch(path + "/archive", json={"is_archived": True})
    assert archived.status_code == 200
    assert archived.json() == {**instrument, "is_archived": True}
    assert client.get(path).json() == archived.json()
    for listing in [
        "/api/v1/instruments",
        f"/api/v1/customers/{customer['id']}/instruments",
    ]:
        assert client.get(listing).json() == []
        assert client.get(listing, params={"include_archived": True}).json() == [
            archived.json()
        ]
    overview = f"/api/v1/customers/{customer['id']}/overview"
    assert client.get(overview).json()["instruments"] == []
    assert client.get(overview, params={"include_archived": True}).json()[
        "instruments"
    ] == [archived.json()]
    assert (
        client.patch(path + "/archive", json={"is_archived": False}).json()
        == instrument
    )
    assert client.get("/api/v1/instruments").json() == [instrument]


def test_archive_combines_filters_and_pagination_counts(archived_instrument_setup):
    client, customer, _, path = archived_instrument_setup
    other = client.post(
        "/api/v1/instruments",
        json={
            "type": "violin",
            "customer_id": customer["id"],
            "identification_number": "ARCHIVE-2",
        },
    ).json()
    client.patch(path + "/archive", json={"is_archived": True})
    params = {
        "q": "archive",
        "type": "violin",
        "customer_id": customer["id"],
        "ownership": "customer",
        "limit": 1,
    }
    active = client.get("/api/v1/instruments", params=params)
    assert active.json() == [other]
    assert active.headers["x-total-count"] == "1"
    archived = client.get(
        "/api/v1/instruments", params={**params, "include_archived": True}
    )
    assert archived.headers["x-total-count"] == "2"
    assert len(archived.json()) == 1
    assert archived.json()[0]["is_archived"]
    assert (
        client.get("/api/v1/instruments", params={**params, "offset": 1}).json() == []
    )
    assert (
        client.get(
            "/api/v1/instruments", params={**params, "include_archived": "invalid"}
        ).status_code
        == 422
    )


def test_archival_preserves_repairs_documents_photos_ownership_and_qr(
    archived_instrument_setup,
):
    client, _, instrument, path = archived_instrument_setup
    storage = FakeStorage()
    client.app.dependency_overrides[get_storage] = lambda: storage
    order = client.post(
        path + "/repair-orders",
        json={
            "work_description": "Historical bridge work",
            "performed_at": "2026-01-01T12:00:00Z",
        },
    ).json()
    document = client.post(
        f"/api/v1/repair-orders/{order['id']}/documents",
        params={"filename": "work.pdf"},
        content=b"Historical document",
        headers={"content-type": "application/octet-stream"},
    ).json()
    photo = client.post(
        path + "/photos", files={"files": ("condition.png", image_bytes(), "image/png")}
    ).json()[0]
    ownership = client.get(path + "/ownership-history").json()
    target = client.get(path + "/qr-code.svg").headers["content-location"]
    public_id = UUID(target.rsplit("/", 1)[1])
    client.patch(path + "/archive", json={"is_archived": True})
    history = client.get(path + "/history").json()
    assert history["instrument"]["is_archived"]
    assert history["repair_orders"][0]["work_description"] == "Historical bridge work"
    assert history["repair_orders"][0]["documents"][0]["id"] == document["id"]
    assert (
        client.get(f"/api/v1/repair-documents/{document['id']}/content").content
        == b"Historical document"
    )
    assert client.get(path + f"/photos/{photo['id']}/content").status_code == 200
    assert client.get(path + "/ownership-history").json() == ownership
    assert client.get(path + "/qr-code.svg").headers["content-location"] == target
    assert client.get(f"/i/{public_id}").json()["id"] == instrument["id"]
    assert storage.deletes == []


@pytest.mark.parametrize("dependent", ["repair", "photo"])
def test_archived_referenced_instruments_cannot_be_deleted(
    archived_instrument_setup, db_connection, dependent
):
    client, _, instrument, path = archived_instrument_setup
    storage = FakeStorage()
    client.app.dependency_overrides[get_storage] = lambda: storage
    if dependent == "repair":
        order = client.post(
            path + "/repair-orders",
            json={
                "work_description": "Retained work",
                "performed_at": "2026-01-01T12:00:00Z",
            },
        ).json()
        assert (
            client.patch(
                f"/api/v1/repair-orders/{order['id']}/archive",
                json={"is_archived": True},
            ).status_code
            == 200
        )
    else:
        photo = client.post(
            path + "/photos",
            files={"files": ("condition.png", image_bytes(), "image/png")},
        ).json()[0]
        assert sign_in(client, "admin").status_code == 200
        assert client.delete(path + f"/photos/{photo['id']}").status_code == 200
    assert (
        client.patch(path + "/archive", json={"is_archived": True}).status_code == 200
    )
    assert client.delete(path).status_code == 409
    assert client.get(path).json()["is_archived"]
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text("DELETE FROM instrument WHERE id = :id"), {"id": instrument["id"]}
            )
        session.rollback()
        events = session.exec(
            select(AuditEvent).where(
                AuditEvent.resource_type == "instrument",
                AuditEvent.resource_id == instrument["id"],
                AuditEvent.action == "instrument.deleted",
            )
        ).all()
        assert events == []
    assert storage.deletes == []


def test_archive_events_are_idempotent_and_attributed(
    archived_instrument_setup, db_connection, accounts
):
    client, _, instrument, path = archived_instrument_setup
    for value in [True, True, False, False]:
        assert (
            client.patch(path + "/archive", json={"is_archived": value}).status_code
            == 200
        )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        events = session.exec(
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == "instrument",
                AuditEvent.resource_id == instrument["id"],
            )
            .order_by(AuditEvent.id)
        ).all()
        assert [event.action for event in events] == [
            "instrument.created",
            "instrument.archived",
            "instrument.restored",
        ]
        assert all(event.actor_id == accounts["employee"] for event in events)
        assert all(event.succeeded for event in events)


def test_archive_and_audit_rollback_together(
    archived_instrument_setup, db_connection, monkeypatch
):
    client, _, instrument, path = archived_instrument_setup

    # Keep the real audit insert and fail the commit, exercising rollback of both.
    original = Session.commit

    def fail_commit(session):
        if any(
            isinstance(row, Instrument) and row.is_archived
            for row in session.identity_map.values()
        ):
            session.flush()
            raise SQLAlchemyError("Simulated archive transaction failure")
        return original(session)

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(SQLAlchemyError):
        client.patch(path + "/archive", json={"is_archived": True})
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Instrument, instrument["id"])
        assert not stored.is_archived
        assert not session.exec(
            select(AuditEvent).where(AuditEvent.action == "instrument.archived")
        ).all()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"is_archived": None},
        {"is_archived": 1},
        {"is_archived": "true"},
        {"is_archived": True, "notes": "other"},
    ],
)
def test_archive_requires_explicit_boolean(archived_instrument_setup, payload):
    client, _, _, path = archived_instrument_setup
    assert client.patch(path + "/archive", json=payload).status_code == 422
    assert not client.get(path).json()["is_archived"]
    assert client.patch(path, json={"is_archived": True}).status_code == 422


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_archive_uses_workshop_authorization(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        sign_in(client, role)
    assert (
        client.patch(
            "/api/v1/instruments/999999/archive", json={"is_archived": True}
        ).status_code
        == expected
    )


def test_archive_keeps_csrf_enforcement(archived_instrument_setup):
    client, _, _, path = archived_instrument_setup
    assert (
        client.patch(
            path + "/archive",
            json={"is_archived": True},
            headers={"Origin": "https://attacker.example"},
        ).status_code
        == 403
    )
    assert not client.get(path).json()["is_archived"]


def test_migration_backfills_false_and_preserves_identifiers(db_connection):
    from pathlib import Path
    from uuid import uuid4

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy.exc import DBAPIError

    schema = "legacy_instrument_archive_" + uuid4().hex
    public_id = uuid4()
    db_connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    db_connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    db_connection.execute(
        text(
            "CREATE TABLE instrument (id integer PRIMARY KEY, public_id uuid NOT NULL, notes text)"
        )
    )
    db_connection.execute(
        text("INSERT INTO instrument VALUES (10, :public_id, 'Retained notes')"),
        {"public_id": public_id},
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("1b9e40f82c67")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.upgrade()
    row = db_connection.execute(
        text("SELECT id, public_id, notes, is_archived FROM instrument")
    ).one()
    assert tuple(row) == (10, public_id, "Retained notes", False)
    db_connection.execute(
        text("INSERT INTO instrument (id, public_id) VALUES (20, :public_id)"),
        {"public_id": uuid4()},
    )
    assert (
        db_connection.scalar(text("SELECT is_archived FROM instrument WHERE id=20"))
        is False
    )
    db_connection.execute(text("UPDATE instrument SET is_archived=true WHERE id=10"))
    with (
        pytest.raises(DBAPIError),
        db_connection.begin_nested(),
        Operations.context(MigrationContext.configure(db_connection)),
    ):
        revision.module.downgrade()
    assert (
        db_connection.scalar(text("SELECT is_archived FROM instrument WHERE id=10"))
        is True
    )
    db_connection.execute(text("UPDATE instrument SET is_archived=false"))
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.downgrade()
    assert (
        db_connection.scalar(text("SELECT public_id FROM instrument WHERE id=10"))
        == public_id
    )


def test_concurrent_archival_records_only_one_event(postgres_engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from atelier_api.instruments.router import set_instrument_archive
    from atelier_api.instruments.schemas import InstrumentArchiveUpdate

    with Session(postgres_engine) as session:
        instrument = Instrument(type="violin")
        session.add(instrument)
        session.flush()
        instrument_id = instrument.id
        session.commit()
    barrier = Barrier(2)

    def archive():
        with Session(postgres_engine) as session:
            barrier.wait(timeout=5)
            return set_instrument_archive(
                instrument_id, InstrumentArchiveUpdate(is_archived=True), session
            ).is_archived

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: archive(), range(2)))
        assert results == [True, True]
        with Session(postgres_engine) as session:
            events = session.exec(
                select(AuditEvent).where(
                    AuditEvent.resource_type == "instrument",
                    AuditEvent.resource_id == instrument_id,
                    AuditEvent.action == "instrument.archived",
                )
            ).all()
            assert len(events) == 1
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM audit_event WHERE resource_type='instrument' AND resource_id=:id"
                ),
                {"id": instrument_id},
            )
            connection.execute(
                text("DELETE FROM instrument WHERE id=:id"), {"id": instrument_id}
            )
            connection.execute(
                text("DELETE FROM instrument_ownership_event WHERE instrument_id=:id"),
                {"id": instrument_id},
            )
