"""Verify customer overview composition and missing-resource behavior."""

import pytest

from atelier_api.customers.models import Customer
from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import InstrumentRead, InstrumentType
from atelier_api.main import app


@pytest.mark.parametrize("archived", [False, True])
def test_overview_includes_customer_details_and_instruments(
    client, mock_session, archived
):
    customer = Customer(
        id=1,
        first_name="Maria",
        last_name="Doe",
        email="maria@example.com",
        is_archived=archived,
    )
    instrument = Instrument(id=2, type=InstrumentType.VIOLIN, customer_id=1)
    mock_session.get.return_value = customer
    mock_session.exec.return_value.all.return_value = [instrument]
    response = client.get("/api/v1/customers/1/overview")
    assert response.status_code == 200
    assert response.json() == {
        "customer": customer.model_dump(mode="json"),
        "instruments": [
            InstrumentRead.model_validate(instrument).model_dump(mode="json")
        ],
    }
    mock_session.get.assert_called_once_with(Customer, 1)
    query = mock_session.exec.call_args.args[0]
    assert "instrument.customer_id =" in str(query)
    assert "ORDER BY instrument.id" in str(query)
    mock_session.commit.assert_not_called()


def test_overview_missing_customer_returns_404(client, mock_session):
    mock_session.get.return_value = None
    response = client.get("/api/v1/customers/999/overview")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    mock_session.exec.assert_not_called()


def test_overview_without_instruments_returns_empty_list(client, mock_session):
    mock_session.get.return_value = Customer(
        id=1, first_name="Maria", last_name="Doe", email="maria@example.com"
    )
    mock_session.exec.return_value.all.return_value = []
    response = client.get("/api/v1/customers/1/overview")
    assert response.status_code == 200
    assert response.json()["instruments"] == []


def test_overview_rejects_invalid_id(client, mock_session):
    assert client.get("/api/v1/customers/invalid/overview").status_code == 422
    mock_session.get.assert_not_called()


def test_overview_is_documented():
    operation = app.openapi()["paths"]["/api/v1/customers/{customer_id}/overview"][
        "get"
    ]
    assert {"200", "404", "422", "503"} <= operation["responses"].keys()
    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/CustomerOverview")
