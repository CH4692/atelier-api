from unittest.mock import MagicMock

import pytest

from atelier_api.customers.models import Customer
from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import InstrumentType
from atelier_api.main import app


@pytest.fixture
def instrument_session(mock_session) -> MagicMock:
    def assign_id(instrument: Instrument) -> None:
        instrument.id = 42

    mock_session.refresh.side_effect = assign_id
    return mock_session


@pytest.mark.parametrize("instrument_type", list(InstrumentType))
def test_register_instrument_without_customer(
    client, instrument_session, instrument_type
):
    response = client.post("/instruments", json={"type": instrument_type.value})
    assert response.status_code == 201
    assert response.json() == {
        "id": 42,
        "type": instrument_type.value,
        "maker": None,
        "year_of_manufacture": None,
        "identification_number": None,
        "notes": None,
        "customer_id": None,
    }
    instrument_session.get.assert_not_called()
    instrument_session.add.assert_called_once()
    instrument_session.commit.assert_called_once()
    saved = instrument_session.add.call_args.args[0]
    assert isinstance(saved, Instrument)
    instrument_session.refresh.assert_called_once_with(saved)


def test_register_instrument_with_existing_customer(client, instrument_session):
    instrument_session.get.return_value = Customer(
        id=7, first_name="Maria", last_name="Doe", email="maria@example.com"
    )
    payload = {
        "type": "violin",
        "maker": "Example maker",
        "year_of_manufacture": 1920,
        "identification_number": "LABEL-42",
        "notes": "Repaired top.",
        "customer_id": 7,
    }
    response = client.post("/instruments", json=payload)
    assert response.status_code == 201
    assert response.json() == {**payload, "id": 42}
    instrument_session.get.assert_called_once_with(Customer, 7)
    saved = instrument_session.add.call_args.args[0]
    assert saved.customer_id == 7
    instrument_session.commit.assert_called_once()


def test_register_instrument_with_explicit_null_customer(client, instrument_session):
    response = client.post("/instruments", json={"type": "viola", "customer_id": None})
    assert response.status_code == 201
    assert response.json()["customer_id"] is None
    instrument_session.get.assert_not_called()


def test_register_instrument_rejects_unknown_customer(client, mock_session):
    mock_session.get.return_value = None
    response = client.post(
        "/instruments", json={"type": "cello", "customer_id": 999999}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    mock_session.get.assert_called_once_with(Customer, 999999)
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"type": "piano"},
        {"type": None},
        {"type": "violin", "year_of_manufacture": 0},
        {"type": "violin", "customer_id": 0},
        {"type": "violin", "customer_id": "invalid"},
        {"type": "violin", "id": 42},
        {"type": "violin", "unexpected": "field"},
    ],
)
def test_register_instrument_rejects_invalid_input(client, mock_session, payload):
    response = client.post("/instruments", json=payload)
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize("body", [b"", b"{invalid json"])
def test_register_instrument_requires_valid_json_body(client, mock_session, body):
    response = client.post(
        "/instruments", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


def test_register_instrument_is_documented_in_openapi():
    operation = app.openapi()["paths"]["/instruments"]["post"]
    assert operation["requestBody"]["required"] is True
    assert {"201", "404", "422", "503"} <= operation["responses"].keys()
    assert operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/InstrumentCreate")
    assert operation["responses"]["201"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/InstrumentRead")


def test_list_instruments_returns_schema_fields(client, mock_session):
    mock_session.exec.return_value.all.return_value = [
        Instrument(
            id=1,
            type=InstrumentType.VIOLIN,
            maker="Example maker",
            year_of_manufacture=1920,
            identification_number="LABEL-42",
            notes="Repaired top.",
            customer_id=7,
        ),
        Instrument(id=2, type=InstrumentType.CELLO),
    ]
    response = client.get("/instruments")
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "type": "violin",
            "maker": "Example maker",
            "year_of_manufacture": 1920,
            "identification_number": "LABEL-42",
            "notes": "Repaired top.",
            "customer_id": 7,
        },
        {
            "id": 2,
            "type": "cello",
            "maker": None,
            "year_of_manufacture": None,
            "identification_number": None,
            "notes": None,
            "customer_id": None,
        },
    ]
    mock_session.exec.assert_called_once()
    mock_session.commit.assert_not_called()


def test_list_instruments_accepts_empty_list(client, mock_session):
    mock_session.exec.return_value.all.return_value = []
    response = client.get("/instruments")
    assert response.status_code == 200
    assert response.json() == []
    mock_session.commit.assert_not_called()


def test_list_instruments_is_documented_as_array_in_openapi():
    operation = app.openapi()["paths"]["/instruments"]["get"]
    assert operation["summary"] == "List registered instruments"
    assert operation["tags"] == ["instruments"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"]["$ref"].endswith("/InstrumentRead")
    assert "503" in operation["responses"]
