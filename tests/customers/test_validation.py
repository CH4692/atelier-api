"""Exercise shared validation and normalization on create and partial update."""

import pytest
from pydantic import ValidationError

from atelier_api.customers.schemas import CustomerCreate, CustomerUpdate


@pytest.mark.parametrize("schema", [CustomerCreate, CustomerUpdate])
@pytest.mark.parametrize(
    "field,value",
    [
        ("first_name", " \t\n"),
        ("last_name", "\u00a0\u2003"),
        ("first_name", "a" * 101),
        ("last_name", None),
        ("email", "invalid"),
        ("email", "a" * 250 + "@example.com"),
        ("phone", "12"),
        ("phone", "+0123456"),
        ("phone", "+" + "1" * 16),
        ("phone", "123 ext 456"),
        ("phone", "１２３４５６"),
        ("phone", " " * 65),
        ("phone", 123),
    ],
)
def test_invalid_customer_fields_are_rejected(schema, field, value):
    data = {"first_name": "Maria", "last_name": "Doe", field: value}
    with pytest.raises(ValidationError):
        schema.model_validate(data)


@pytest.mark.parametrize("schema", [CustomerCreate, CustomerUpdate])
def test_names_trim_before_length_validation_and_preserve_internal_spaces(schema):
    data = schema(first_name=" \u00a0" + "A" * 100 + "\t", last_name=" van der Doe ")
    assert data.first_name == "A" * 100
    assert data.last_name == "van der Doe"


@pytest.mark.parametrize("schema", [CustomerCreate, CustomerUpdate])
@pytest.mark.parametrize(
    "phone,expected",
    [
        ("+49 (176) 123-45.67", "+491761234567"),
        ("0049 176/1234567", "+491761234567"),
        ("0176 1234567", "01761234567"),
        ("+" + "1" * 15, "+" + "1" * 15),
        (None, None),
        (" \t", None),
    ],
)
def test_phone_normalization(schema, phone, expected):
    data = schema(first_name="Maria", last_name="Doe", phone=phone)
    assert data.phone == expected


@pytest.mark.parametrize("email", [None, "", " \t"])
def test_optional_email_can_be_cleared(email):
    data = CustomerUpdate(email=email)
    assert data.model_dump(exclude_unset=True) == {"email": None}


def test_contacts_are_optional_and_email_is_normalized():
    data = CustomerCreate(first_name="Maria", last_name="Doe")
    assert data.email is None and data.phone is None
    data = CustomerCreate(
        first_name="Maria", last_name="Doe", email="  Maria@EXAMPLE.COM "
    )
    assert data.email == "Maria@example.com"
    assert CustomerUpdate().model_dump(exclude_unset=True) == {}


def test_email_length_boundary():
    address = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 57 + ".com"
    assert len(address) == 254
    assert (
        CustomerCreate(first_name="Maria", last_name="Doe", email=address).email
        == address
    )
    with pytest.raises(ValidationError):
        CustomerCreate(first_name="Maria", last_name="Doe", email="x" + address)


@pytest.mark.parametrize(
    "method,path", [("POST", "/api/v1/customers"), ("PATCH", "/api/v1/customers/1")]
)
@pytest.mark.parametrize(
    "invalid",
    [
        {"first_name": "  "},
        {"last_name": "a" * 101},
        {"email": "bad"},
        {"phone": "bad"},
    ],
)
def test_invalid_http_input_returns_422_without_database_writes(
    client, mock_session, method, path, invalid
):
    payload = {"first_name": "Maria", "last_name": "Doe", **invalid}
    assert client.request(method, path, json=payload).status_code == 422
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


def test_patch_can_clear_email(client, mock_session):
    from atelier_api.customers.models import Customer

    mock_session.get.return_value = Customer(
        id=1, first_name="Maria", last_name="Doe", email="maria@example.com"
    )
    response = client.patch("/api/v1/customers/1", json={"email": None})
    assert response.status_code == 200
    assert response.json()["email"] is None
