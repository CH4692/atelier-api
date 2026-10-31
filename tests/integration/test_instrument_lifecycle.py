import pytest
from sqlmodel import Session

from atelier_api.instruments.models import Instrument
from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration


@pytest.mark.e2e
def test_instrument_management_lifecycle(auth_factory, db_connection):
    client = auth_factory()
    assert sign_in(client, "employee").status_code == 200
    customers = []
    for name in ("Jon", "Maria"):
        response = client.post(
            "/api/v1/customers",
            json={
                "first_name": name,
                "last_name": "Doe",
                "email": f"{name.lower()}@example.com",
            },
        )
        assert response.status_code == 201
        customers.append(response.json())
    first_customer, next_customer = customers
    first_list = f"/api/v1/customers/{first_customer['id']}/instruments"
    next_list = f"/api/v1/customers/{next_customer['id']}/instruments"
    response = client.post(
        "/api/v1/instruments",
        json={
            "type": "violin",
            "maker": "Example maker",
            "year_of_manufacture": 1920,
            "identification_number": "LIFECYCLE-1",
            "notes": "Registered instrument.",
            "customer_id": first_customer["id"],
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert isinstance(created["id"], int)
    assert created["id"] > 0
    path = f"/api/v1/instruments/{created['id']}"
    for list_path in ("/api/v1/instruments", first_list):
        response = client.get(list_path)
        assert response.status_code == 200
        assert response.json() == [created]
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == created

    changes = {"notes": "Transferred instrument.", "customer_id": next_customer["id"]}
    response = client.patch(path, json=changes)
    assert response.status_code == 200
    updated = {**created, **changes}
    assert response.json() == updated
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Instrument, created["id"])
        assert stored is not None
        assert stored.model_dump(mode="json", exclude={"public_id"}) == updated
        assert stored.customer is not None
        assert stored.customer.id == next_customer["id"]
    assert client.get(first_list).json() == []
    assert client.get(next_list).json() == [updated]

    response = client.patch(path, json={"type": "piano"})
    assert response.status_code == 422
    assert client.get(path).json() == updated
    response = client.delete(path)
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/v1/instruments").json() == []
    assert client.get(next_list).json() == []
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert session.get(Instrument, created["id"]) is None
    for method, payload in [
        ("GET", None),
        ("PATCH", {"notes": "Already deleted."}),
        ("DELETE", None),
    ]:
        response = client.request(method, path, json=payload)
        assert response.status_code == 404
        assert response.json() == {"detail": "Instrument not found"}
    for customer in customers:
        assert client.get(f"/api/v1/customers/{customer['id']}").status_code == 200
