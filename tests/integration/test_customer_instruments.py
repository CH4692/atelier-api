import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def instrument_owners(postgres_client):
    customers = []
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
        customers.append(response.json())
    return customers


def test_customer_list_excludes_other_customers_and_unassigned_instruments(
    postgres_client, instrument_owners
):
    first, second = instrument_owners
    expected = {first["id"]: [], second["id"]: []}
    for instrument_type, customer_id in [
        ("violin", first["id"]),
        ("viola", first["id"]),
        ("cello", second["id"]),
        ("double_bass", None),
    ]:
        response = postgres_client.post(
            "/instruments",
            json={
                "type": instrument_type,
                "customer_id": customer_id,
                "maker": "Example maker",
                "year_of_manufacture": 1920,
                "identification_number": f"LABEL-{instrument_type}",
                "notes": "Recorded details.",
            },
        )
        assert response.status_code == 201
        if customer_id is not None:
            expected[customer_id].append(response.json())
    for customer in instrument_owners:
        response = postgres_client.get(f"/customers/{customer['id']}/instruments")
        assert response.status_code == 200
        records = response.json()
        assert len(records) == len(expected[customer["id"]])
        assert {item["id"]: item for item in records} == {
            item["id"]: item for item in expected[customer["id"]]
        }
        assert all(item["customer_id"] == customer["id"] for item in records)


def test_existing_customer_without_instruments_returns_empty_list(
    postgres_client, instrument_owners
):
    first, second = instrument_owners
    response = postgres_client.post(
        "/instruments", json={"type": "cello", "customer_id": second["id"]}
    )
    assert response.status_code == 201
    response = postgres_client.get(f"/customers/{first['id']}/instruments")
    assert response.status_code == 200
    assert response.json() == []


def test_unknown_customer_returns_404_from_postgresql(postgres_client):
    response = postgres_client.get("/customers/999999/instruments")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}


def test_customer_instrument_lists_follow_current_association(
    postgres_client, instrument_owners
):
    first, second = instrument_owners
    response = postgres_client.post(
        "/instruments", json={"type": "violin", "customer_id": first["id"]}
    )
    assert response.status_code == 201
    instrument = response.json()
    first_path = f"/customers/{first['id']}/instruments"
    second_path = f"/customers/{second['id']}/instruments"
    assert postgres_client.get(first_path).json() == [instrument]
    assert postgres_client.get(second_path).json() == []
    response = postgres_client.patch(
        f"/instruments/{instrument['id']}", json={"customer_id": second["id"]}
    )
    assert response.status_code == 200
    reassigned = response.json()
    assert postgres_client.get(first_path).json() == []
    assert postgres_client.get(second_path).json() == [reassigned]
    response = postgres_client.patch(
        f"/instruments/{instrument['id']}", json={"customer_id": None}
    )
    assert response.status_code == 200
    assert postgres_client.get(first_path).json() == []
    assert postgres_client.get(second_path).json() == []
    assert postgres_client.get(f"/instruments/{instrument['id']}").status_code == 200
