"""Validate customer names and optional normalized contact information."""

import re

from pydantic import EmailStr, StrictBool, field_validator
from sqlalchemy import String
from sqlmodel import Field, SQLModel


class CustomerValidation(SQLModel):
    """Share normalization between creation, partial updates and responses."""

    @field_validator("first_name", "last_name", mode="before", check_fields=False)
    @classmethod
    def normalize_name(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Name must be non-empty text")
        return value.strip()

    @field_validator("email", mode="before", check_fields=False)
    @classmethod
    def normalize_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("phone", mode="before", check_fields=False)
    @classmethod
    def normalize_phone(cls, value: object) -> str | None:
        """Strip formatting without guessing a country code or accepting extensions."""
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError("Telephone must be text of at most 64 characters")
        if not value.strip():
            return None
        number = re.sub(r"[\s()./\-]", "", value)
        if number.startswith("00"):
            number = "+" + number[2:]
        if not re.fullmatch(r"(?:\+[1-9][0-9]{2,14}|[0-9]{3,15})", number):
            raise ValueError(
                "Telephone must contain 3–15 digits and an optional international prefix"
            )
        return number


class CustomerBase(CustomerValidation):
    """Share bounded fields across API schemas and the table model."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=64, sa_type=String(16))


class CustomerRead(CustomerBase):
    """Represent a stored customer, including archive state."""

    id: int
    is_archived: bool = False


class CustomerArchiveUpdate(SQLModel):
    """Set archive state independently of personal details and permanent deletion."""

    model_config = {"extra": "forbid"}
    is_archived: StrictBool


class CustomerCreate(CustomerBase):
    """Accept names and optional contact details without a client-supplied ID."""


class CustomerUpdate(CustomerValidation):
    """Preserve omitted fields; clear contacts with null or blank text.

    Supplied names cannot be null. Unknown fields are rejected.
    """

    model_config = {"extra": "forbid"}
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: EmailStr | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=64)
