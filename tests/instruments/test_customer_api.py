import pytest

from atelier_api.customers.models import Customer
from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import InstrumentType
from atelier_api.main import app


def test_customer_instruments_return_instrument_schema(client, mock_session):
    mock_session.get.return_value = Customer(
        id=7, first_name="Maria", last_name="Doe", email="maria@example.com"
    )
    mock_session.exec.return_value.all.return_value = [
        Instrument(
            id=42,
            type=InstrumentType.VIOLIN,
            maker="Example maker",
            year_of_manufacture=1920,
            identification_number="LABEL-42",
            notes="Repaired top.",
            customer_id=7,
        ),
    ]
    response = client.get("/api/v1/customers/7/instruments")
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 42,
            "type": "violin",
            "maker": "Example maker",
            "year_of_manufacture": 1920,
            "identification_number": "LABEL-42",
            "notes": "Repaired top.",
            "customer_id": 7,
            "ownership": "customer",
        }
    ]
    mock_session.get.assert_called_once_with(Customer, 7)
    mock_session.exec.assert_called_once()
    mock_session.commit.assert_not_called()


def test_customer_without_instruments_returns_empty_list(client, mock_session):
    mock_session.get.return_value = Customer(
        id=7, first_name="Maria", last_name="Doe", email="maria@example.com"
    )
    mock_session.exec.return_value.all.return_value = []
    response = client.get("/api/v1/customers/7/instruments")
    assert response.status_code == 200
    assert response.json() == []
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize("customer_id", [0, -1, 999999])
def test_unknown_customer_instrument_list_returns_404(
    client, mock_session, customer_id
):
    mock_session.get.return_value = None
    response = client.get(f"/api/v1/customers/{customer_id}/instruments")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    mock_session.get.assert_called_once_with(Customer, customer_id)
    mock_session.exec.assert_not_called()
    mock_session.commit.assert_not_called()


def test_customer_instrument_list_rejects_invalid_id(client, mock_session):
    response = client.get("/api/v1/customers/invalid/instruments")
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.exec.assert_not_called()


def test_customer_instruments_are_documented_in_openapi():
    operation = app.openapi()["paths"]["/api/v1/customers/{customer_id}/instruments"][
        "get"
    ]
    assert {"200", "404", "422", "503"} <= operation["responses"].keys()
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"]["$ref"].endswith("/InstrumentRead")
    assert operation["tags"] == ["customers"]
