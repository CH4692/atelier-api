import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from atelier_api.customers.models import Customer
from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import (
    InstrumentCreate,
    InstrumentRead,
    InstrumentType,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def instrument_customer_id(db_connection):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        customer = Customer(
            first_name="Maria", last_name="Müller", email="maria@example.com"
        )
        session.add(customer)
        session.commit()
        session.refresh(customer)
        return customer.id


def test_instrument_details_and_customer_relationship_persist(
    db_connection, instrument_customer_id
):
    payload = InstrumentCreate(
        type=InstrumentType.VIOLIN,
        maker="Example maker",
        year_of_manufacture=1920,
        identification_number="LABEL-42",
        notes="Repaired top; handwritten label.",
        customer_id=instrument_customer_id,
    )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        instrument = Instrument.model_validate(payload)
        session.add(instrument)
        session.commit()
        session.refresh(instrument)
        instrument_id = instrument.id
        assert isinstance(instrument_id, int)

    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Instrument, instrument_id)
        assert stored is not None
        assert stored.type is InstrumentType.VIOLIN
        assert stored.customer is not None
        assert stored.customer.id == instrument_customer_id
        assert InstrumentRead.model_validate(stored).model_dump(mode="json") == {
            **payload.model_dump(mode="json"),
            "id": instrument_id,
        }


@pytest.mark.parametrize("instrument_type", list(InstrumentType))
def test_instrument_can_exist_without_customer(db_connection, instrument_type):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        instrument = Instrument.model_validate(InstrumentCreate(type=instrument_type))
        session.add(instrument)
        session.commit()
        session.refresh(instrument)
        assert instrument.id is not None
        assert instrument.type == instrument_type
        assert instrument.customer_id is None
        assert instrument.customer is None


def test_customer_can_have_multiple_instruments(db_connection, instrument_customer_id):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        for instrument_type in (InstrumentType.VIOLIN, InstrumentType.CELLO):
            session.add(
                Instrument(type=instrument_type, customer_id=instrument_customer_id)
            )
        session.commit()
        instruments = session.exec(
            select(Instrument).where(Instrument.customer_id == instrument_customer_id)
        ).all()
        assert {instrument.type for instrument in instruments} == {
            InstrumentType.VIOLIN,
            InstrumentType.CELLO,
        }
        assert all(
            instrument.customer.id == instrument_customer_id
            for instrument in instruments
        )


def test_unknown_customer_is_rejected_by_foreign_key(db_connection):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        session.add(Instrument(type=InstrumentType.CELLO, customer_id=999999))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_customer_deletion_keeps_instrument_and_clears_association(
    postgres_client, db_connection, instrument_customer_id
):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        instrument = Instrument(
            type=InstrumentType.VIOLA,
            identification_number="KEEP-42",
            customer_id=instrument_customer_id,
        )
        session.add(instrument)
        session.commit()
        session.refresh(instrument)
        instrument_id = instrument.id
    response = postgres_client.delete(f"/api/v1/customers/{instrument_customer_id}")
    assert response.status_code == 204
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Instrument, instrument_id)
        assert stored is not None
        assert stored.identification_number == "KEEP-42"
        assert stored.customer_id is None
        assert stored.customer is None
        assert session.get(Customer, instrument_customer_id) is None


@pytest.mark.parametrize(
    "instrument_type, year",
    [
        (None, 1920),
        ("piano", 1920),
        ("violin", 0),
        ("violin", 10000),
    ],
)
def test_database_constraints_reject_invalid_direct_writes(
    db_connection, instrument_type, year
):
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text(
                "INSERT INTO instrument (type, year_of_manufacture) VALUES (:type, :year)"
            ),
            {"type": instrument_type, "year": year},
        )
