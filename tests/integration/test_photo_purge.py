from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from atelier_api.audit.models import AuditEvent
from atelier_api.instruments.models import Instrument
from atelier_api.photos.models import InstrumentPhoto
from atelier_api.photos.purge import claim_photo, purge_photos, retention_statistics
from atelier_api.settings import Settings
from tests.photos.helpers import FakeStorage

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def configuration(**changes):
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        photo_auto_purge_enabled=True,
        **changes,
    )


@pytest.fixture
def committed_photos(postgres_engine):
    """Commit real rows so independent PostgreSQL workers can observe each other."""
    storage = FakeStorage()
    with Session(postgres_engine) as session:
        instrument = Instrument(type="violin", ownership="workshop")
        session.add(instrument)
        session.flush()
        instrument_id = instrument.id
        public_id = instrument.public_id
        session.commit()

    def create(*, status="deleted", age=31, approved=True, hold=False, key=None):
        with Session(postgres_engine, expire_on_commit=False) as session:
            photo = InstrumentPhoto(
                instrument_id=instrument_id,
                storage_namespace=storage.namespace,
                storage_key=key or f"instruments/{public_id}/{uuid4()}.png",
                original_filename="Private original.png",
                content_type="image/png",
                file_size_bytes=42,
                status=status,
                uploaded_at=NOW - timedelta(days=100),
                deletion_requested_at=NOW - timedelta(days=age)
                if status in {"deleted", "purging"}
                else None,
                purge_approved_at=NOW if approved else None,
                retention_hold_reason="Evidence" if hold else None,
                retention_hold_at=NOW if hold else None,
            )
            session.add(photo)
            session.commit()
            storage.objects[photo.storage_key] = b"x" * 42
            return photo

    try:
        yield postgres_engine, storage, create
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM audit_event WHERE resource_type = 'instrument_photo' AND details->>'instrument_id' = :id"
                ),
                {"id": str(instrument_id)},
            )
            connection.execute(
                text("DELETE FROM instrument_photo WHERE instrument_id = :id"),
                {"id": instrument_id},
            )
            connection.execute(
                text("DELETE FROM instrument WHERE id = :id"), {"id": instrument_id}
            )
            connection.execute(
                text(
                    "DELETE FROM instrument_ownership_event WHERE instrument_id = :id"
                ),
                {"id": instrument_id},
            )


def current(engine, photo_id):
    with Session(engine) as session:
        return session.get(InstrumentPhoto, photo_id)


def events(engine, action):
    with Session(engine) as session:
        return session.exec(select(AuditEvent).where(AuditEvent.action == action)).all()


def run(engine, storage, **changes):
    return purge_photos(engine, storage, configuration(), now=NOW, **changes)


def test_only_reviewed_expired_unprotected_photos_are_purged(committed_photos):
    engine, storage, create = committed_photos
    eligible = create()
    boundary = create(age=30)
    active = create(status="ready")
    young = create(age=29)
    held = create(hold=True)
    unreviewed = create(approved=False)
    summary = run(engine, storage)
    assert summary.eligible == summary.processed == summary.purged == 2
    assert summary.bytes_freed == 84
    assert (
        summary.protected == summary.unreviewed == summary.active == summary.young == 1
    )
    assert not current(engine, eligible.id)
    assert not current(engine, boundary.id)
    for photo in [active, young, held, unreviewed]:
        assert current(engine, photo.id)
        assert storage.exists(photo.storage_key)
    assert len(events(engine, "instrument_photo.purge_started")) == 2
    assert len(events(engine, "instrument_photo.purged")) == 2
    assert run(engine, storage).purged == 0


def test_custom_retention_and_statistics_are_read_only(committed_photos):
    engine, storage, create = committed_photos
    photo = create(age=3)
    config = configuration(photo_soft_delete_retention_days=2)
    with Session(engine) as session:
        summary = retention_statistics(session, config, storage.namespace, NOW)
    assert summary.eligible == 1
    assert summary.eligible_bytes == 42
    assert current(engine, photo.id).status == "deleted"
    assert not storage.deletes
    assert not events(engine, "instrument_photo.purge_started")


def test_disabled_execution_and_batch_limit(committed_photos):
    engine, storage, create = committed_photos
    create()
    create()
    disabled = Settings(_env_file=None, database_url="sqlite://")
    with pytest.raises(ValueError, match="disabled"):
        purge_photos(engine, storage, disabled)
    assert not storage.deletes
    assert run(engine, storage, limit=1).purged == 1
    assert run(engine, storage, limit=1).purged == 1


@pytest.mark.parametrize(
    "key",
    [
        "../../other.png",
        "instruments/00000000-0000-0000-0000-000000000000/secret.png",
        "instruments/active/photo.png",
    ],
)
def test_wrong_object_identity_never_reaches_storage(committed_photos, key):
    engine, storage, create = committed_photos
    photo = create(key=key)
    result = run(engine, storage)
    assert result.invalid_identity == 1
    assert result.result == "failed"
    assert not storage.deletes
    assert current(engine, photo.id).status == "deleted"


def test_missing_object_can_finalize_after_authorized_exact_delete(committed_photos):
    engine, storage, create = committed_photos
    photo = create()
    storage.objects.clear()
    assert run(engine, storage).purged == 1
    assert storage.deletes == [photo.storage_key]
    assert current(engine, photo.id) is None


def test_failed_storage_keeps_nonrestorable_claim_and_retry_finishes(committed_photos):
    engine, storage, create = committed_photos
    photo = create()
    storage.fail_delete = True
    failed = run(engine, storage)
    assert failed.failed == 1
    assert failed.purged == 0
    assert current(engine, photo.id).status == "purging"
    assert len(events(engine, "instrument_photo.purge_started")) == 1
    assert len(events(engine, "instrument_photo.purge_failed")) == 1
    storage.fail_delete = False
    recovered = run(engine, storage)
    assert recovered.purged == recovered.recovered_claims == 1
    assert current(engine, photo.id) is None
    assert len(events(engine, "instrument_photo.purge_started")) == 1
    assert len(events(engine, "instrument_photo.purged")) == 1


def test_finalization_failure_recovers_after_object_is_gone(
    committed_photos, monkeypatch
):
    from atelier_api.photos import purge

    engine, storage, create = committed_photos
    photo = create()
    original = purge.finalize_purge

    def fail(*args):
        raise SQLAlchemyError("Sensitive DB error")

    monkeypatch.setattr(purge, "finalize_purge", fail)
    assert run(engine, storage).failed == 1
    assert not storage.objects
    assert current(engine, photo.id).status == "purging"
    monkeypatch.setattr(purge, "finalize_purge", original)
    assert run(engine, storage).purged == 1
    assert len(events(engine, "instrument_photo.purged")) == 1


def test_interrupted_claim_is_recovered(committed_photos):
    engine, storage, create = committed_photos
    photo = create()
    with Session(engine) as session:
        assert claim_photo(
            session, storage, configuration(), photo.id, str(uuid4()), NOW
        )
    assert current(engine, photo.id).status == "purging"
    assert run(engine, storage).recovered_claims == 1
    assert current(engine, photo.id) is None


def test_multiple_workers_do_not_delete_same_object(committed_photos, monkeypatch):
    engine, storage, create = committed_photos
    photo = create()
    deleting = Event()
    proceed = Event()
    original = storage.delete

    def blocked(key):
        deleting.set()
        assert proceed.wait(5)
        original(key)

    monkeypatch.setattr(storage, "delete", blocked)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(run, engine, storage)
        assert deleting.wait(5)
        second = workers.submit(run, engine, storage).result(timeout=5)
        assert second.purged == 0
        assert second.skipped == 1
        proceed.set()
        assert first.result(timeout=5).purged == 1
    assert storage.deletes == [photo.storage_key]
    assert len(events(engine, "instrument_photo.purged")) == 1


def test_no_database_transaction_is_open_during_storage_io(
    committed_photos, monkeypatch
):
    from atelier_api.photos import purge

    engine, storage, create = committed_photos
    create()
    original_claim = purge.claim_photo
    original_delete = storage.delete
    session_used = []

    def capture(session, *args):
        result = original_claim(session, *args)
        session_used.append(session)
        return result

    def verify_no_transaction(key):
        assert not session_used[-1].in_transaction()
        assert not session_used[-1].bind.in_transaction()
        original_delete(key)

    monkeypatch.setattr(purge, "claim_photo", capture)
    monkeypatch.setattr(storage, "delete", verify_no_transaction)
    assert run(engine, storage).purged == 1


def test_restore_wins_before_claim_and_purge_skips(committed_photos, monkeypatch):
    from atelier_api.photos import purge
    from atelier_api.photos.retention import restore_photo

    engine, storage, create = committed_photos
    photo = create(age=2)
    monkeypatch.setattr("atelier_api.photos.retention.utc_now", lambda: NOW)
    selecting = Event()
    proceed = Event()
    original_claim = purge.claim_photo

    def pause(*args):
        selecting.set()
        assert proceed.wait(5)
        return original_claim(*args)

    monkeypatch.setattr(purge, "claim_photo", pause)
    with ThreadPoolExecutor(max_workers=1) as worker:
        job = worker.submit(
            purge_photos,
            engine,
            storage,
            configuration(photo_soft_delete_retention_days=1),
            now=NOW,
        )
        assert selecting.wait(5)
        with Session(engine) as session:
            restored = restore_photo(
                session, storage, configuration(), photo.instrument_id, photo.id, None
            )
            assert restored.status == "ready"
        proceed.set()
        assert job.result(timeout=5).purged == 0
    assert storage.exists(photo.storage_key)
    assert current(engine, photo.id).status == "ready"


def test_purge_wins_while_restore_checks_object(committed_photos, monkeypatch):
    from fastapi import HTTPException

    from atelier_api.photos.retention import restore_photo

    engine, storage, create = committed_photos
    photo = create(age=2)
    monkeypatch.setattr("atelier_api.photos.retention.utc_now", lambda: NOW)
    checking = Event()
    proceed = Event()
    original_exists = storage.exists

    def pause_first_check(key):
        present = original_exists(key)
        if not checking.is_set():
            checking.set()
            assert proceed.wait(5)
        return present

    def restore():
        with Session(engine) as session:
            return restore_photo(
                session, storage, configuration(), photo.instrument_id, photo.id, None
            )

    monkeypatch.setattr(storage, "exists", pause_first_check)
    with ThreadPoolExecutor(max_workers=1) as worker:
        restoration = worker.submit(restore)
        assert checking.wait(5)
        assert (
            purge_photos(
                engine,
                storage,
                configuration(photo_soft_delete_retention_days=1),
                now=NOW,
            ).purged
            == 1
        )
        proceed.set()
        with pytest.raises(HTTPException) as error:
            restoration.result(timeout=5)
        assert error.value.status_code in {404, 409}
    assert not events(engine, "instrument_photo.restored")
    assert not storage.objects


def test_hold_wins_before_claim_and_purge_skips(committed_photos, monkeypatch):
    from atelier_api.photos import purge
    from atelier_api.photos.retention import manage_hold

    engine, storage, create = committed_photos
    photo = create()
    selecting = Event()
    proceed = Event()
    original_claim = purge.claim_photo

    def pause(*args):
        selecting.set()
        assert proceed.wait(5)
        return original_claim(*args)

    monkeypatch.setattr(purge, "claim_photo", pause)
    with ThreadPoolExecutor(max_workers=1) as worker:
        job = worker.submit(run, engine, storage)
        assert selecting.wait(5)
        with Session(engine) as session:
            manage_hold(session, photo.instrument_id, photo.id, None, "Dispute")
        proceed.set()
        assert job.result(timeout=5).purged == 0
    assert not storage.deletes
    assert current(engine, photo.id).retention_hold_reason == "Dispute"


def test_remaining_object_is_not_marked_purged(committed_photos, monkeypatch):
    engine, storage, create = committed_photos
    photo = create()
    monkeypatch.setattr(storage, "delete", lambda key: None)
    result = run(engine, storage)
    assert result.failed == 1
    assert current(engine, photo.id).status == "purging"
    assert not events(engine, "instrument_photo.purged")


def test_stale_claim_finalizes_even_if_policy_was_lengthened(committed_photos):
    engine, storage, create = committed_photos
    photo = create(status="purging", age=1)
    storage.objects.clear()
    result = run(engine, storage)
    assert result.purged == result.recovered_claims == 1
    assert current(engine, photo.id) is None


def test_wrong_storage_namespace_never_deletes(committed_photos):
    engine, storage, create = committed_photos
    photo = create()
    storage.namespace = "different-location"
    result = run(engine, storage)
    assert result.wrong_storage == 1
    assert result.result == "failed"
    assert not storage.deletes
    assert current(engine, photo.id).status == "deleted"


def test_dry_run_cli_without_storage_is_read_only(
    committed_photos, monkeypatch, capsys
):
    import json

    from atelier_api.photos import purge_cli

    engine, storage, create = committed_photos
    photo = create(age=1000)
    monkeypatch.setattr(
        "sys.argv", ["atelier-photos-purge", "--dry-run", "--limit", "1"]
    )
    monkeypatch.setattr(purge_cli, "engine", engine)
    monkeypatch.setattr(
        purge_cli, "settings", Settings(_env_file=None, database_url="sqlite://")
    )
    purge_cli.main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["eligible"] == 1
    assert summary["eligible_bytes"] == 42
    assert summary["dry_run"]
    assert not summary["storage_configured"]
    assert not storage.deletes
    assert current(engine, photo.id).status == "deleted"
    assert not events(engine, "instrument_photo.purge_started")


def test_one_storage_failure_does_not_hide_subsequent_work(
    committed_photos, monkeypatch
):
    from atelier_api.photos.storage import StorageError

    engine, storage, create = committed_photos
    first = create()
    second = create()
    original = storage.delete

    def fail_one(key):
        if key == first.storage_key:
            raise StorageError
        original(key)

    monkeypatch.setattr(storage, "delete", fail_one)
    result = run(engine, storage)
    assert result.processed == 2
    assert result.failed == result.purged == 1
    assert current(engine, first.id).status == "purging"
    assert current(engine, second.id) is None


def test_failed_absence_check_never_marks_purged(committed_photos, monkeypatch):
    from atelier_api.photos.storage import StorageError

    engine, storage, create = committed_photos
    photo = create()
    original = storage.exists

    def unavailable(key):
        raise StorageError

    monkeypatch.setattr(storage, "exists", unavailable)
    assert run(engine, storage).failed == 1
    assert current(engine, photo.id).status == "purging"
    assert not events(engine, "instrument_photo.purged")
    monkeypatch.setattr(storage, "exists", original)
    assert run(engine, storage).purged == 1


def test_retention_migration_preserves_data_and_guards_holds(postgres_engine):
    import os
    import subprocess
    import sys

    from sqlalchemy import create_engine

    schema = "retention_migration_" + uuid4().hex
    with postgres_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = postgres_engine.url.update_query_dict(
        {"options": "-csearch_path=" + schema}
    )
    engine = create_engine(scoped_url)

    def migrate(*args, success=True):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env={
                **os.environ,
                "DATABASE_URL": scoped_url.render_as_string(hide_password=False),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        assert (result.returncode == 0) == success, result.stderr
        return result

    try:
        migrate("upgrade", "f97c28d60a45")
        with engine.begin() as connection:
            instrument_id = connection.scalar(
                text(
                    "INSERT INTO instrument (type, ownership) VALUES ('violin', 'workshop') RETURNING id"
                )
            )
            photo_id = connection.scalar(
                text("""INSERT INTO instrument_photo
                (instrument_id, storage_namespace, storage_key, original_filename, content_type, file_size_bytes, uploaded_at, status, deletion_requested_at)
                VALUES (:instrument, 'test-storage', 'existing-key', 'Original.png', 'image/png', 42, :now, 'deleted', :now) RETURNING id"""),
                {"instrument": instrument_id, "now": NOW},
            )
        migrate("upgrade", "head")
        with engine.begin() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM instrument_photo WHERE id = :id"),
                    {"id": photo_id},
                )
                .mappings()
                .one()
            )
            assert row["storage_key"] == "existing-key"
            assert row["original_filename"] == "Original.png"
            assert row["deletion_requested_at"] == NOW
            assert row["purge_approved_at"] is None
            assert row["retention_hold_reason"] is None
            connection.execute(
                text(
                    "UPDATE instrument_photo SET retention_hold_reason = 'Evidence', retention_hold_at = :now WHERE id = :id"
                ),
                {"id": photo_id, "now": NOW},
            )
        failed = migrate("downgrade", "-1", success=False)
        assert "Reconcile purging photographs and retention holds" in failed.stderr
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE instrument_photo SET retention_hold_reason = NULL, retention_hold_at = NULL WHERE id = :id"
                ),
                {"id": photo_id},
            )
        migrate("downgrade", "-1")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM instrument_photo")) == 1
        migrate("upgrade", "head")
        migrate("check")
    finally:
        engine.dispose()
        with postgres_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
