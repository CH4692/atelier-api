import pytest
from sqlmodel import Session, select

from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import InstrumentType

pytestmark = pytest.mark.integration


def test_register_instrument_persists_details_and_customer(
    postgres_client, db_connection
):
    response = postgres_client.post(
        "/api/v1/customers",
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
    response = postgres_client.post("/api/v1/instruments", json=payload)
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
    response = postgres_client.post("/api/v1/instruments", json={"type": "double_bass"})
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
    response = postgres_client.post("/api/v1/instruments", json=payload)
    assert response.status_code == status_code
    if status_code == 404:
        assert response.json() == {"detail": "Customer not found"}
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert session.exec(select(Instrument)).all() == []


def test_list_instruments_returns_registered_records(postgres_client):
    response = postgres_client.post(
        "/api/v1/customers",
        json={
            "first_name": "Maria",
            "last_name": "Doe",
            "email": "maria@example.com",
        },
    )
    assert response.status_code == 201
    customer_id = response.json()["id"]
    created = []
    for payload in [
        {
            "type": "violin",
            "maker": "Example maker",
            "year_of_manufacture": 1920,
            "identification_number": "LABEL-42",
            "notes": "Repaired top.",
            "customer_id": customer_id,
        },
        {"type": "cello"},
    ]:
        response = postgres_client.post("/api/v1/instruments", json=payload)
        assert response.status_code == 201
        created.append(response.json())

    response = postgres_client.get("/api/v1/instruments")
    assert response.status_code == 200
    records = response.json()
    assert isinstance(records, list)
    assert len(records) == 2
    assert {record["id"]: record for record in records} == {
        record["id"]: record for record in created
    }


def test_list_instruments_returns_empty_list_from_postgresql(postgres_client):
    response = postgres_client.get("/api/v1/instruments")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("with_customer", [True, False])
def test_get_registered_instrument_by_id(postgres_client, with_customer):
    customer_id = None
    if with_customer:
        response = postgres_client.post(
            "/api/v1/customers",
            json={
                "first_name": "Maria",
                "last_name": "Doe",
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
    response = postgres_client.post("/api/v1/instruments", json=payload)
    assert response.status_code == 201
    created = response.json()
    path = f"/api/v1/instruments/{created['id']}"
    response = postgres_client.get(path)
    assert response.status_code == 200
    assert response.json() == created
    assert response.json()["customer_id"] == customer_id

    if with_customer:
        response = postgres_client.delete(f"/api/v1/customers/{customer_id}")
        assert response.status_code == 204
        response = postgres_client.get(path)
        assert response.status_code == 200
        assert response.json() == {**created, "customer_id": None}


def test_get_unknown_instrument_returns_404_from_postgresql(postgres_client):
    response = postgres_client.get("/api/v1/instruments/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Instrument not found"}


def test_update_instrument_persists_details_and_customer_changes(
    postgres_client, db_connection
):
    customer_ids = []
    for name in ("Jon", "Maria"):
        response = postgres_client.post(
            "/api/v1/customers",
            json={
                "first_name": name,
                "last_name": "Doe",
                "email": f"{name.lower()}@example.com",
            },
        )
        assert response.status_code == 201
        customer_ids.append(response.json()["id"])
    response = postgres_client.post(
        "/api/v1/instruments",
        json={
            "type": "violin",
            "maker": "Original maker",
            "year_of_manufacture": 1920,
            "identification_number": "LABEL-42",
            "notes": "Original notes.",
            "customer_id": customer_ids[0],
        },
    )
    assert response.status_code == 201
    created = response.json()
    path = f"/api/v1/instruments/{created['id']}"
    changes = {
        "type": "viola",
        "maker": "Updated maker",
        "year_of_manufacture": 1930,
        "identification_number": "LABEL-43",
        "notes": "Updated notes.",
        "customer_id": customer_ids[1],
    }
    response = postgres_client.patch(path, json=changes)
    assert response.status_code == 200
    expected = {**created, **changes}
    assert response.json() == expected
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Instrument, created["id"])
        assert stored is not None
        assert stored.model_dump(mode="json") == expected
        assert stored.customer is not None
        assert stored.customer.id == customer_ids[1]
    assert postgres_client.get(path).json() == expected

    response = postgres_client.patch(path, json={"notes": "Only notes changed."})
    assert response.status_code == 200
    expected["notes"] = "Only notes changed."
    assert response.json() == expected
    cleared = {
        field: None
        for field in (
            "maker",
            "year_of_manufacture",
            "identification_number",
            "notes",
            "customer_id",
        )
    }
    response = postgres_client.patch(path, json=cleared)
    assert response.status_code == 200
    expected.update(cleared)
    assert response.json() == expected
    assert postgres_client.get(path).json() == expected
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Instrument, created["id"])
        assert stored is not None
        assert stored.customer is None
        assert stored.customer_id is None
        assert stored.type is InstrumentType.VIOLA
    response = postgres_client.patch(path, json={"customer_id": customer_ids[0]})
    assert response.status_code == 200
    expected["customer_id"] = customer_ids[0]
    assert response.json() == expected
    assert postgres_client.get(path).json() == expected


@pytest.mark.parametrize(
    "changes, status_code",
    [
        ({"customer_id": 999999, "notes": "Should not change."}, 404),
        ({"type": None, "notes": "Should not change."}, 422),
        ({"year_of_manufacture": 0}, 422),
    ],
)
def test_failed_instrument_update_preserves_stored_data(
    postgres_client, changes, status_code
):
    response = postgres_client.post(
        "/api/v1/instruments", json={"type": "cello", "notes": "Original notes."}
    )
    assert response.status_code == 201
    created = response.json()
    path = f"/api/v1/instruments/{created['id']}"
    response = postgres_client.patch(path, json=changes)
    assert response.status_code == status_code
    assert postgres_client.get(path).json() == created


def test_update_unknown_instrument_returns_404_from_postgresql(postgres_client):
    response = postgres_client.patch(
        "/api/v1/instruments/999999", json={"notes": "Changed notes."}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Instrument not found"}
    assert postgres_client.get("/api/v1/instruments").json() == []


@pytest.mark.parametrize("with_customer", [True, False])
def test_delete_instrument_removes_record_and_preserves_other_data(
    postgres_client, db_connection, with_customer
):
    customer_id = None
    if with_customer:
        response = postgres_client.post(
            "/api/v1/customers",
            json={
                "first_name": "Maria",
                "last_name": "Doe",
                "email": "maria@example.com",
            },
        )
        assert response.status_code == 201
        customer_id = response.json()["id"]
    instruments = []
    for instrument_type in ("violin", "cello"):
        response = postgres_client.post(
            "/api/v1/instruments",
            json={
                "type": instrument_type,
                "customer_id": customer_id,
            },
        )
        assert response.status_code == 201
        instruments.append(response.json())
    deleted, retained = instruments
    path = f"/api/v1/instruments/{deleted['id']}"
    response = postgres_client.delete(path)
    assert response.status_code == 204
    assert response.content == b""
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert session.get(Instrument, deleted["id"]) is None
        assert session.get(Instrument, retained["id"]) is not None
    response = postgres_client.get(path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Instrument not found"}
    response = postgres_client.get("/api/v1/instruments")
    assert response.status_code == 200
    assert response.json() == [retained]
    assert (
        postgres_client.get(f"/api/v1/instruments/{retained['id']}").json() == retained
    )
    response = postgres_client.delete(path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Instrument not found"}
    assert postgres_client.get("/api/v1/instruments").json() == [retained]
    if with_customer:
        response = postgres_client.get(f"/api/v1/customers/{customer_id}")
        assert response.status_code == 200
        assert response.json()["id"] == customer_id


def test_delete_unknown_instrument_does_not_change_database(postgres_client):
    response = postgres_client.delete("/api/v1/instruments/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Instrument not found"}
    assert postgres_client.get("/api/v1/instruments").json() == []
