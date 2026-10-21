from fastapi.testclient import TestClient
from unittest.mock import patch
from unittest.mock import MagicMock
from atelier_api.database import get_session 
from atelier_api.main import app
from customers.schemas import CustomerRead, CustomerCreate

import pytest

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



testdata_customers : list[CustomerRead] = [ 
    CustomerRead(
        id=1,
        first_name="Jon",
        last_name="Doe",
        email="jon.doe@example.com", 
        phone="+49176123456789"
    ),
    CustomerRead(
        id=2,
        first_name="Maria",
        last_name="Doe",
        email="maria.doe@example.de",
        phone="+49123456789"
    )
]

client = TestClient(app)

def test_get_customers(mock_session):
   # 2. Definiere, was session.exec().all() zurückgeben soll
    mock_session.exec.return_value.all.return_value = testdata_customers
    response = client.get("/customers")
    assert response.status_code == 200
    expected_json = [CustomerRead.model_validate(c).model_dump() for c in testdata_customers]
    assert response.json() == expected_json

# test test_create_customer
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

    # Act: HTTP-Request ausführen
    response = client.post("/customers", json=payload)
    # Assert: HTTP-Antwort prüfen

    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "first_name": "Jon",
        "last_name": "Doe",
        "email": "jon.doe@example.com",
        "phone": "+49176123456789",
    }

    # Assert: Datenbankoperationen prüfen
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once()

def test_create_customer_without_required_fields(mock_session):
    payload = {}
    response = client.post("/customers", json=payload)
    assert response.status_code == 422
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()

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



