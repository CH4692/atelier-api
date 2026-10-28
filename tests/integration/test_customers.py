import pytest
from sqlmodel import Session, select

from atelier_api.customers.models import Customer

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("phone", [None, "+49176123456789"])
def test_create_and_retrieve_customer(postgres_client, db_connection, phone):
    payload = {
        "first_name": "Maria",
        "last_name": "Müller",
        "email": "maria@example.com",
        "phone": phone,
    }
    response = postgres_client.post("/customers", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert isinstance(created["id"], int)
    assert created["id"] > 0
    assert created == {**payload, "id": created["id"]}

    # This session shares no identity map with the session used by the POST request.
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Customer, created["id"])
        assert stored is not None
        assert stored.model_dump() == created

    response = postgres_client.get(f"/customers/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created
    response = postgres_client.get("/customers")
    assert response.status_code == 200
    assert response.json() == [created]


def test_customer_list_starts_empty(postgres_client):
    response = postgres_client.get("/customers")
    assert response.status_code == 200
    assert response.json() == []


def test_committed_test_data_does_not_leak(postgres_client, db_connection):
    assert postgres_client.get("/customers").json() == []
    for name in ("Jon", "Maria"):
        response = postgres_client.post(
            "/customers",
            json={
                "first_name": name,
                "last_name": "Doe",
                "email": f"{name.lower()}@example.com",
            },
        )
        assert response.status_code == 201
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert len(session.exec(select(Customer)).all()) == 2


def test_missing_customer_returns_404(postgres_client):
    response = postgres_client.get("/customers/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}


def test_invalid_customer_is_not_persisted(postgres_client):
    response = postgres_client.post(
        "/customers",
        json={
            "first_name": "Jon",
            "last_name": "Doe",
            "email": "invalid",
        },
    )
    assert response.status_code == 422
    assert postgres_client.get("/customers").json() == []
