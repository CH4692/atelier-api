from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from atelier_api.customers.models import Customer
from atelier_api.customers.schemas import CustomerRead
from atelier_api.database import get_session
from atelier_api.main import app


@pytest.fixture
def mock_session():
    session = MagicMock()
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = lambda: session
    yield session
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)


testdata_customers: list[Customer] = [
    Customer(
        id=1,
        first_name="Jon",
        last_name="Doe",
        email="jon.doe@example.com",
        phone="+49176123456789",
    ),
    Customer(
        id=2,
        first_name="Maria",
        last_name="Doe",
        email="maria.doe@example.de",
        phone="+49123456789",
    ),
]
test_customer = Customer(
    id=1,
    first_name="Jon",
    last_name="Doe",
    email="jon.doe@example.com",
    phone="+49176123456789",
)

client = TestClient(app)


def test_get_customers(mock_session):
    mock_session.exec.return_value.all.return_value = testdata_customers
    response = client.get("/customers")
    assert response.status_code == 200
    expected_json = [
        CustomerRead.model_validate(c).model_dump() for c in testdata_customers
    ]
    assert response.json() == expected_json


def test_get_customer_by_id(mock_session):
    mock_session.get.return_value = test_customer
    response = client.get("/customers/1")
    assert response.status_code == 200
    expected_json = CustomerRead.model_validate(test_customer).model_dump(mode="json")
    assert response.json() == expected_json
    mock_session.get.assert_called_once_with(Customer, 1)


def test_get_customer_by_id_not_found(mock_session):
    mock_session.get.return_value = None
    response = client.get("/customers/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    mock_session.get.assert_called_once_with(Customer, 999)


def test_get_customer_by_id_invalid_id(mock_session):
    response = client.get("/customers/abc")
    assert response.status_code == 422
    mock_session.get.assert_not_called()


@pytest.mark.parametrize(
    "customer_id",
    [0, -1, 999999],
)
def test_get_customer_by_id_not_found_for_boundary_values(
    mock_session,
    customer_id,
):
    mock_session.get.return_value = None
    response = client.get(f"/customers/{customer_id}")
    assert response.status_code == 404
    mock_session.get.assert_called_once_with(
        Customer,
        customer_id,
    )


def test_create_customer(mock_session):
    payload = {
        "first_name": "Jon",
        "last_name": "Doe",
        "email": "jon.doe@example.com",
        "phone": "+49176123456789",
    }

    def refresh_customer(customer):
        customer.id = 1

    mock_session.refresh.side_effect = refresh_customer
    response = client.post("/customers", json=payload)
    assert response.status_code == 201
    mock_session.add.assert_called_once()
    saved_customer = mock_session.add.call_args.args[0]
    assert isinstance(saved_customer, Customer)
    assert saved_customer.first_name == payload["first_name"]
    assert saved_customer.last_name == payload["last_name"]
    assert saved_customer.email == payload["email"]
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once_with(saved_customer)


def test_get_customers_empty(mock_session):
    mock_session.exec.return_value.all.return_value = []
    response = client.get("/customers")
    assert response.status_code == 200
    assert response.json() == []


def test_create_customer_missing_required_fields(mock_session):
    response = client.post("/customers", json={})
    assert response.status_code == 422
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


def test_create_customer_invalid_email(mock_session):
    payload = {
        "first_name": "Jon",
        "last_name": "Doe",
        "email": "keine-gueltige-email",
        "phone": "+49176123456789",
    }

    response = client.post("/customers", json=payload)
    assert response.status_code == 422
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.fixture
def update_target(mock_session):
    # Use a new instance so updates cannot mutate shared test data.
    customer = Customer(
        id=1,
        first_name="Jon",
        last_name="Doe",
        email="jon.doe@example.com",
        phone="+49176123456789",
    )
    mock_session.get.return_value = customer
    return customer


def test_update_customer_all_fields(mock_session, update_target):
    payload = {
        "first_name": "Maria",
        "last_name": "Müller",
        "email": "maria@example.com",
        "phone": "+49123456789",
    }
    response = client.patch("/customers/1", json=payload)
    assert response.status_code == 200
    assert response.json() == {"id": 1, **payload}
    mock_session.get.assert_called_once_with(Customer, 1)
    mock_session.add.assert_called_once_with(update_target)
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once_with(update_target)


def test_update_customer_preserves_omitted_fields(mock_session, update_target):
    before = update_target.model_dump()
    response = client.patch("/customers/1", json={"first_name": "  Maria  "})
    assert response.status_code == 200
    assert response.json() == {**before, "first_name": "Maria"}
    mock_session.commit.assert_called_once()


def test_update_customer_can_clear_phone(mock_session, update_target):
    response = client.patch("/customers/1", json={"phone": None})
    assert response.status_code == 200
    assert response.json()["phone"] is None
    mock_session.commit.assert_called_once()


def test_update_customer_empty_body_is_noop(mock_session, update_target):
    response = client.patch("/customers/1", json={})
    assert response.status_code == 200
    assert response.json() == update_target.model_dump()
    mock_session.commit.assert_not_called()


def test_update_customer_unknown_id(mock_session):
    mock_session.get.return_value = None
    response = client.patch("/customers/999", json={"first_name": "Maria"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "invalid"},
        {"email": None},
        {"first_name": None},
        {"last_name": None},
        {"first_name": ""},
        {"last_name": "   "},
        {"first_name": 123},
        {"phone": 123},
        {"id": 2},
        {"unknown": "value"},
    ],
)
def test_update_customer_rejects_invalid_data(mock_session, payload):
    response = client.patch("/customers/1", json=payload)
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.commit.assert_not_called()


def test_update_customer_rejects_invalid_id(mock_session):
    response = client.patch("/customers/abc", json={"first_name": "Maria"})
    assert response.status_code == 422
    mock_session.get.assert_not_called()


def test_update_customer_requires_request_body(mock_session):
    response = client.patch("/customers/1")
    assert response.status_code == 422
    mock_session.commit.assert_not_called()


def test_update_customer_documented_in_openapi():
    operation = app.openapi()["paths"]["/customers/{customer_id}"]["patch"]
    assert operation["requestBody"]["required"] is True
    assert {"200", "404", "422"} <= operation["responses"].keys()
    assert operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/CustomerUpdate")


def test_delete_customer_returns_empty_204(mock_session, update_target):
    response = client.delete("/customers/1")
    assert response.status_code == 204
    assert response.content == b""
    mock_session.get.assert_called_once_with(Customer, 1)
    mock_session.delete.assert_called_once_with(update_target)
    mock_session.commit.assert_called_once()


def test_delete_customer_unknown_id(mock_session):
    mock_session.get.return_value = None
    response = client.delete("/customers/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    mock_session.delete.assert_not_called()
    mock_session.commit.assert_not_called()


def test_delete_customer_invalid_id(mock_session):
    response = client.delete("/customers/abc")
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.delete.assert_not_called()
    mock_session.commit.assert_not_called()


def test_delete_customer_documented_in_openapi():
    operation = app.openapi()["paths"]["/customers/{customer_id}"]["delete"]
    assert {"204", "404", "422", "503"} <= operation["responses"].keys()
    assert "content" not in operation["responses"]["204"]
    assert "requestBody" not in operation
