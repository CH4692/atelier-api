import pytest

from fastapi.testclient import TestClient
from pydantic import ValidationError
from customers.models import BaseCustomer
from atelier_api.main import app

client = TestClient(app)

@pytest.fixture
def customer_data():
    """Liefert für jeden Test gültige Kundendaten"""
    return {
        "id": 1,
        "first_name": "Charles",
        "last_name": "Heller",
        "email": "charles.heller@hotmail.de",
        "phone": "+49176123456789",
    }

def test_accepts_valid_customer(customer_data):
    customer = BaseCustomer(**customer_data)
    assert customer.model_dump() == customer_data

@pytest.mark.parametrize(
    "field",
    ["id", "first_name", "last_name", "email"]
)
def test_rejects_missing_required_field(customer_data, field):
    # deletes the item out of the dictionary
    del customer_data[field]

    with pytest.raises(ValidationError) as error:
        BaseCustomer(**customer_data)

    assert any(
        issue["loc"] == (field, ) and issue["type"] == "missing" 
        for issue in error.value.errors()
    )

@pytest.mark.parametrize(
    "email",
    ["keine-email", "name@", "@example.com"]
)
def test_rejects_invalid_email(customer_data, email):
    customer_data["email"] = email

    with pytest.raises(ValidationError) as error:
        BaseCustomer(**customer_data)

    assert any(
        issue["loc"] == ("email",)
        for issue in error.value.errors()
    )