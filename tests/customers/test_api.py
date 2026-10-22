from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from atelier_api.database import get_session
from atelier_api.main import app
from customers.schemas import CustomerRead
from customers.models import Customer


# 1. Erstelle eine Fixture für die Mock-Datenbank-Session
@pytest.fixture
def mock_session():
    session = MagicMock()
    original_overrides = app.dependency_overrides.copy()
    # FastAPI überschreiben
    # (Ersetze 'get_session' mit der Funktion, die deine SessionDep erzeugt)
    app.dependency_overrides[get_session] = lambda: session
    yield session
    # Nach dem Test das Override wieder aufräumen
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)



testdata_customers : list[Customer] = [ 
    Customer(
        id=1,
        first_name="Jon",
        last_name="Doe",
        email="jon.doe@example.com", 
        phone="+49176123456789"
    ),
    Customer(
        id=2,
        first_name="Maria",
        last_name="Doe",
        email="maria.doe@example.de",
        phone="+49123456789"
    )
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
   # 2. Definiere, was session.exec().all() zurückgeben soll
    mock_session.exec.return_value.all.return_value = testdata_customers
    response = client.get("/customers")
    assert response.status_code == 200
    expected_json = [CustomerRead.model_validate(c).model_dump() for c in testdata_customers]
    assert response.json() == expected_json

def test_get_customer_by_id(mock_session):
    # Arrange
    mock_session.get.return_value = test_customer
    # Act
    response = client.get("/customers/1")
    # Assert
    assert response.status_code == 200
    expected_json = CustomerRead.model_validate(
        test_customer
    ).model_dump(mode="json")
    assert response.json() == expected_json
    mock_session.get.assert_called_once_with(Customer, 1)

def test_get_customer_by_id_not_found(mock_session):
    # Arrange
    mock_session.get.return_value = None
    # Act
    response = client.get("/customers/999")
    # Assert
    assert response.status_code == 404
    assert response.json() == {
        "detail": "Customer not found"
    }
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

# test test_create_customer
def test_create_customer(mock_session):
    # Arrange
    payload = {
        "first_name": "Jon",
        "last_name": "Doe",
        "email": "jon.doe@example.com",
        "phone": "+49176123456789",
    }
    def refresh_customer(customer):
        customer.id = 1
    mock_session.refresh.side_effect = refresh_customer
    # Act
    response = client.post("/customers", json=payload)
    # Assert
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





