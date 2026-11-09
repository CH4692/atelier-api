"""Verify demo imports against migrated PostgreSQL, real auth and private storage."""

from datetime import date, timedelta
from hashlib import sha256

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import func, text
from sqlmodel import Session, select

from atelier_api.customers.models import Customer
from atelier_api.demo import service
from atelier_api.demo.photos import seed_photos
from atelier_api.instruments.models import Instrument
from atelier_api.photos.models import InstrumentPhoto
from atelier_api.repair_orders.item_service import list_items
from atelier_api.repair_orders.models import RepairDocument, RepairOrder
from atelier_api.repair_orders.statuses import RepairStatus
from atelier_api.settings import Settings
from atelier_api.users.authentication import authenticate_user
from atelier_api.users.models import User, UserProvisioningState
from tests.photos.helpers import FakeStorage

REFERENCE = date(2026, 11, 9)
PASSWORD = SecretStr("Only-for-isolated-demo-tests-42!")


def config_for(connection):
    return Settings(
        _env_file=None,
        database_url=connection.engine.url.render_as_string(hide_password=False),
    )


def count(session, model):
    return session.exec(select(func.count()).select_from(model)).one()


def test_small_seed_relations_auth_chronology_and_non_destructive_repeat(
    db_connection, postgres_client
):
    config = config_for(db_connection)
    # IDs must come from persisted references, not the profile's ordinal numbers.
    db_connection.execute(
        text("SELECT nextval(pg_get_serial_sequence('customer', 'id'))")
    )
    report = service.seed_small(
        db_connection, config, password=PASSWORD, as_of=REFERENCE
    )
    assert report.counts == {
        "customers": 50,
        "instruments": 100,
        "repairs": 150,
        "documents": 30,
        "users": 6,
        "internal_users": 5,
        "portal_users": 1,
        "templates": 12,
        "repair_items": 210,
        "estimates": 25,
        "photos": 0,
        "rentals": 0,
        "invoices": 0,
        "payments": 0,
    }
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        instruments = session.exec(select(Instrument).order_by(Instrument.id)).all()
        assert len({row.public_id for row in instruments}) == 100
        assert all(row.public_id.version == 4 for row in instruments)
        by_id = {row.id: row for row in instruments}
        orders = session.exec(select(RepairOrder)).all()
        assert {row.status for row in orders} == set(RepairStatus)
        assert min(row.created_at.date() for row in orders) < REFERENCE - timedelta(
            days=3 * 365
        )
        for row in orders:
            assert row.customer_id == by_id[row.instrument_id].customer_id
            assert row.accepted_at is not None and row.status_updated_at is not None
            assert row.created_at <= row.accepted_at <= row.status_updated_at
            assert row.status_updated_at.date() <= REFERENCE
            year = by_id[row.instrument_id].year_of_manufacture
            assert year is None or year <= row.created_at.year
            if row.status == RepairStatus.COMPLETED:
                assert (
                    row.performed_at is not None and row.performed_at >= row.accepted_at
                )
            else:
                assert row.performed_at is None
        for document in session.exec(select(RepairDocument)):
            assert document.size_bytes == len(document.content)
            assert document.sha256 == sha256(document.content).hexdigest()
            assert "FIKTIVER DEMOBELEG" in document.content.decode()
        assert orders[0].id is not None
        totals = list_items(session, orders[0].id)
        assert totals.total == totals.service_total + totals.material_total
        assert (
            authenticate_user(
                "meister.demo@example.com", PASSWORD.get_secret_value(), session
            )
            is not None
        )
        assert (
            authenticate_user(
                "pausiert.demo@example.com", PASSWORD.get_secret_value(), session
            )
            is None
        )
        assert (
            authenticate_user(
                "kunde.demo@example.com", PASSWORD.get_secret_value(), session
            )
            is None
        )
        assert (
            authenticate_user(
                "kunde.demo@example.com",
                PASSWORD.get_secret_value(),
                session,
                allow_customer=True,
            )
            is not None
        )
        hashes = [
            user.hashed_password
            for user in session.exec(select(User).order_by(User.id))
        ]
        instruments[2].maker = "Manuelle Demoänderung"
        session.add(instruments[2])
        session.commit()
    repeated = service.seed_small(db_connection, config, password=None)
    assert (
        repeated.reused
        and repeated.counts == report.counts
        and repeated.as_of == REFERENCE
    )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert [
            user.hashed_password
            for user in session.exec(select(User).order_by(User.id))
        ] == hashes
        assert session.exec(
            select(Instrument).where(Instrument.maker == "Manuelle Demoänderung")
        ).one()
    customers = postgres_client.get("/api/v1/customers?limit=25")
    assert customers.status_code == 200
    assert int(customers.headers["X-Total-Count"]) == 46
    ready = postgres_client.get("/api/v1/repairs?status=ready_for_pickup")
    assert ready.status_code == 200 and len(ready.json()) == 10
    with pytest.raises(ValueError, match="reference date"):
        service.seed_small(db_connection, config, password=None, as_of=date(2027, 1, 1))


def test_seed_failure_rolls_back_service_commits_and_bootstrap_latch(
    db_connection, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("injected seed failure")

    monkeypatch.setattr(service, "_estimates", fail)
    with pytest.raises(RuntimeError, match="injected"), db_connection.begin_nested():
        service.seed_small(
            db_connection, config_for(db_connection), password=PASSWORD, as_of=REFERENCE
        )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        for model in (Customer, Instrument, RepairOrder, User):
            assert count(session, model) == 0
        assert session.get(UserProvisioningState, 1).bootstrap_completed is False


def test_seed_refuses_existing_records_without_changing_them(db_connection):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        session.add(Customer(first_name="Vorhanden", last_name="Unverändert"))
        session.commit()
    with pytest.raises(ValueError, match="existing records"):
        service.seed_small(db_connection, config_for(db_connection), password=PASSWORD)
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert count(session, Customer) == 1
        assert count(session, User) == 0


def test_demo_photos_resume_real_uploads_after_failure_without_duplicates(
    db_connection,
):
    config = config_for(db_connection)
    service.seed_small(db_connection, config, password=PASSWORD, as_of=REFERENCE)
    storage = FakeStorage()
    storage.fail_upload_number = 2
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        with pytest.raises(HTTPException) as failure:
            seed_photos(session, config, storage)
        assert failure.value.status_code == 503
        assert count(session, Customer) == 50
        assert count(session, InstrumentPhoto) == 1
        storage.fail_upload_number = None
        assert seed_photos(session, config, storage) == 50
        uploads = len(storage.uploads)
        assert seed_photos(session, config, storage) == 50
        assert len(storage.uploads) == uploads
        photos = session.exec(select(InstrumentPhoto)).all()
        assert len(photos) == len(storage.objects) == 50
        assert all(
            photo.status == "ready"
            and photo.file_size_bytes == len(storage.objects[photo.storage_key])
            for photo in photos
        )
        # Never hide a missing object by creating duplicate or fabricated metadata.
        storage.objects.pop(photos[0].storage_key)
        with pytest.raises(ValueError, match="binary is missing"):
            seed_photos(session, config, storage)
