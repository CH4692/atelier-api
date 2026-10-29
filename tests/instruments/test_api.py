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


@pytest.mark.parametrize("customer_id", [7, None])
def test_get_instrument_returns_details_and_customer_id(
    client, mock_session, customer_id
):
    mock_session.get.return_value = Instrument(
        id=42,
        type=InstrumentType.VIOLIN,
        maker="Example maker",
        year_of_manufacture=1920,
        identification_number="LABEL-42",
        notes="Repaired top.",
        customer_id=customer_id,
    )
    response = client.get("/instruments/42")
    assert response.status_code == 200
    assert response.json() == {
        "id": 42,
        "type": "violin",
        "maker": "Example maker",
        "year_of_manufacture": 1920,
        "identification_number": "LABEL-42",
        "notes": "Repaired top.",
        "customer_id": customer_id,
    }
    mock_session.get.assert_called_once_with(Instrument, 42)
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize("instrument_id", [0, -1, 999999])
def test_get_unknown_instrument_returns_404(client, mock_session, instrument_id):
    mock_session.get.return_value = None
    response = client.get(f"/instruments/{instrument_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Instrument not found"}
    mock_session.get.assert_called_once_with(Instrument, instrument_id)
    mock_session.commit.assert_not_called()


def test_get_instrument_rejects_invalid_id(client, mock_session):
    response = client.get("/instruments/invalid")
    assert response.status_code == 422
    mock_session.get.assert_not_called()


def test_get_instrument_is_documented_in_openapi():
    operation = app.openapi()["paths"]["/instruments/{instrument_id}"]["get"]
    assert {"200", "404", "422", "503"} <= operation["responses"].keys()
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/InstrumentRead")
    (parameter,) = operation["parameters"]
    assert parameter["name"] == "instrument_id"
    assert parameter["in"] == "path"
    assert parameter["required"] is True


@pytest.fixture
def update_instrument_target(mock_session):
    instrument = Instrument(
        id=42,
        type=InstrumentType.VIOLIN,
        maker="Original maker",
        year_of_manufacture=1920,
        identification_number="LABEL-42",
        notes="Original notes.",
        customer_id=7,
    )
    mock_session.get.return_value = instrument
    return instrument


def test_update_instrument_changes_details(
    client, mock_session, update_instrument_target
):
    payload = {
        "type": "viola",
        "maker": "Updated maker",
        "year_of_manufacture": 1930,
        "identification_number": "LABEL-43",
        "notes": "Updated notes.",
    }
    response = client.patch("/instruments/42", json=payload)
    assert response.status_code == 200
    assert response.json() == {"id": 42, "customer_id": 7, **payload}
    mock_session.get.assert_called_once_with(Instrument, 42)
    mock_session.add.assert_called_once_with(update_instrument_target)
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once_with(update_instrument_target)


def test_update_instrument_preserves_omitted_fields(
    client, mock_session, update_instrument_target
):
    before = update_instrument_target.model_dump(mode="json")
    response = client.patch("/instruments/42", json={"notes": "Changed notes."})
    assert response.status_code == 200
    assert response.json() == {**before, "notes": "Changed notes."}
    mock_session.get.assert_called_once_with(Instrument, 42)


def test_update_instrument_changes_customer(
    client, mock_session, update_instrument_target
):
    customer = Customer(
        id=8, first_name="Maria", last_name="Doe", email="maria@example.com"
    )
    mock_session.get.side_effect = [update_instrument_target, customer]
    response = client.patch("/instruments/42", json={"customer_id": 8})
    assert response.status_code == 200
    assert response.json()["customer_id"] == 8
    assert mock_session.get.call_args_list[0].args == (Instrument, 42)
    assert mock_session.get.call_args_list[1].args == (Customer, 8)
    mock_session.commit.assert_called_once()


def test_update_instrument_clears_optional_fields(
    client, mock_session, update_instrument_target
):
    payload = {
        name: None
        for name in (
            "maker",
            "year_of_manufacture",
            "identification_number",
            "notes",
            "customer_id",
        )
    }
    response = client.patch("/instruments/42", json=payload)
    assert response.status_code == 200
    assert response.json() == {"id": 42, "type": "violin", **payload}
    mock_session.get.assert_called_once_with(Instrument, 42)
    mock_session.commit.assert_called_once()


def test_update_instrument_empty_body_is_noop(
    client, mock_session, update_instrument_target
):
    before = update_instrument_target.model_dump(mode="json")
    response = client.patch("/instruments/42", json={})
    assert response.status_code == 200
    assert response.json() == before
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


def test_update_unknown_instrument_returns_404(client, mock_session):
    mock_session.get.return_value = None
    response = client.patch("/instruments/999999", json={"notes": "Changed notes."})
    assert response.status_code == 404
    assert response.json() == {"detail": "Instrument not found"}
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


def test_update_instrument_rejects_unknown_customer_before_mutating_record(
    client, mock_session, update_instrument_target
):
    before = update_instrument_target.model_dump(mode="json")
    mock_session.get.side_effect = [update_instrument_target, None]
    response = client.patch(
        "/instruments/42", json={"customer_id": 999999, "notes": "Changed notes."}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    assert update_instrument_target.model_dump(mode="json") == before
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"type": None},
        {"type": "piano"},
        {"year_of_manufacture": 0},
        {"year_of_manufacture": 10000},
        {"year_of_manufacture": "invalid"},
        {"customer_id": 0},
        {"customer_id": -1},
        {"customer_id": "invalid"},
        {"maker": 123},
        {"notes": ["invalid"]},
        {"id": 43},
        {"unexpected": "value"},
    ],
)
def test_update_instrument_rejects_invalid_input(client, mock_session, payload):
    response = client.patch("/instruments/42", json=payload)
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.commit.assert_not_called()


def test_update_instrument_rejects_invalid_id(client, mock_session):
    response = client.patch("/instruments/invalid", json={"notes": "Changed notes."})
    assert response.status_code == 422
    mock_session.get.assert_not_called()


def test_update_instrument_requires_body(client, mock_session):
    response = client.patch("/instruments/42")
    assert response.status_code == 422
    mock_session.commit.assert_not_called()


def test_update_instrument_is_documented_in_openapi():
    operation = app.openapi()["paths"]["/instruments/{instrument_id}"]["patch"]
    assert {"200", "404", "422", "503"} <= operation["responses"].keys()
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/InstrumentUpdate")
    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/InstrumentRead")


def test_delete_instrument_returns_empty_204(
    client, mock_session, update_instrument_target
):
    response = client.delete("/instruments/42")
    assert response.status_code == 204
    assert response.content == b""
    mock_session.get.assert_called_once_with(Instrument, 42)
    mock_session.delete.assert_called_once_with(update_instrument_target)
    mock_session.commit.assert_called_once()


@pytest.mark.parametrize("instrument_id", [0, -1, 999999])
def test_delete_unknown_instrument_returns_404(client, mock_session, instrument_id):
    mock_session.get.return_value = None
    response = client.delete(f"/instruments/{instrument_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Instrument not found"}
    mock_session.delete.assert_not_called()
    mock_session.commit.assert_not_called()


def test_delete_instrument_rejects_invalid_id(client, mock_session):
    response = client.delete("/instruments/invalid")
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.delete.assert_not_called()
    mock_session.commit.assert_not_called()


def test_delete_instrument_is_documented_in_openapi():
    operation = app.openapi()["paths"]["/instruments/{instrument_id}"]["delete"]
    assert {"204", "404", "422", "503"} <= operation["responses"].keys()
    assert "content" not in operation["responses"]["204"]
    assert "requestBody" not in operation
