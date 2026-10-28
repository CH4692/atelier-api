import pytest
from sqlmodel import Session, select

from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import InstrumentType

pytestmark = pytest.mark.integration


def test_register_instrument_persists_details_and_customer(
    postgres_client, db_connection
):
    response = postgres_client.post(
        "/customers",
        json={
            "first_name": "Maria",
            "last_name": "Müller",
            "email": "maria@example.com",
        },
    )
    assert response.status_code == 201
    customer_id = response.json()["id"]
    payload = {
        "type": "violin",
        "maker": "Example maker",
        "year_of_manufacture": 1920,
        "identification_number": "LABEL-42",
        "notes": "Repaired top.",
        "customer_id": customer_id,
    }
    response = postgres_client.post("/instruments", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert isinstance(created["id"], int)
    assert created["id"] > 0
    assert created == {**payload, "id": created["id"]}
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Instrument, created["id"])
        assert stored is not None
        assert stored.customer is not None
        assert stored.customer.id == customer_id
        assert stored.type is InstrumentType.VIOLIN
        assert stored.model_dump(mode="json") == created


def test_register_unassigned_instrument_persists_without_customer(
    postgres_client, db_connection
):
    response = postgres_client.post("/instruments", json={"type": "double_bass"})
    assert response.status_code == 201
    created = response.json()
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Instrument, created["id"])
        assert stored is not None
        assert stored.type is InstrumentType.DOUBLE_BASS
        assert stored.customer_id is None
        assert stored.customer is None


@pytest.mark.parametrize(
    "payload, status_code",
    [
        ({"type": "cello", "customer_id": 999999}, 404),
        ({"type": "piano"}, 422),
        ({"type": "violin", "year_of_manufacture": 0}, 422),
    ],
)
def test_rejected_registration_does_not_create_instrument(
    postgres_client, db_connection, payload, status_code
):
    response = postgres_client.post("/instruments", json=payload)
    assert response.status_code == status_code
    if status_code == 404:
        assert response.json() == {"detail": "Customer not found"}
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert session.exec(select(Instrument)).all() == []
