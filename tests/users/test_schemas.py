import pytest
from pydantic import ValidationError

from atelier_api.users.models import User
from atelier_api.users.passwords import hash_password
from atelier_api.users.schemas import UserCreate, UserRead


def test_user_input_normalizes_email_and_masks_password():
    user = UserCreate(email=" Admin@Example.COM ", password="test-password-123")
    assert user.email == "admin@example.com"
    assert user.is_active is True
    assert "test-password-123" not in repr(user)
    assert "password" not in user.model_dump()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "admin@example.com"},
        {"email": "invalid", "password": "test-password-123"},
        {"email": "admin@example.com", "password": "short"},
        {"email": "admin@example.com", "password": ""},
        {"email": "admin@example.com", "password": "x" * 1025},
        {
            "email": "admin@example.com",
            "password": "test-password-123",
            "hashed_password": "not-allowed",
        },
    ],
)
def test_invalid_user_input_is_rejected(payload):
    with pytest.raises(ValidationError):
        UserCreate.model_validate(payload)


def test_password_hash_is_not_in_serialized_user_or_repr():
    encoded = hash_password("test-password-123")
    user = User.model_validate(
        {"id": 1, "email": "admin@example.com", "hashed_password": encoded}
    )
    assert "password" not in User.model_fields
    assert encoded not in repr(user)
    assert "hashed_password" not in user.model_dump()
    public_user = UserRead.model_validate(user)
    assert set(public_user.model_dump()) == {
        "id",
        "email",
        "is_active",
        "role",
        "customer_id",
        "created_at",
        "updated_at",
    }


def test_password_validation_error_does_not_echo_plaintext():
    with pytest.raises(ValidationError) as error:
        UserCreate(email="admin@example.com", password="shortsecret")
    assert "shortsecret" not in str(error.value)


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"customer_id": 1}])
def test_user_input_cannot_assign_privileged_fields(extra):
    with pytest.raises(ValidationError):
        UserCreate.model_validate(
            {"email": "employee@example.com", "password": "test-password-123", **extra}
        )
