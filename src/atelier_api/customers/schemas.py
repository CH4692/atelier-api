"""Define customer API payloads and field validation."""

from pydantic import EmailStr, StrictBool, field_validator
from sqlmodel import SQLModel


class CustomerBase(SQLModel):
    """Share customer fields across API schemas and the table model."""

    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None = None


class CustomerRead(CustomerBase):
    """Represent a stored customer, including its identifier."""

    id: int
    is_archived: bool = False


class CustomerArchiveUpdate(SQLModel):
    """Set archive state independently of personal details and permanent deletion."""

    model_config = {"extra": "forbid"}
    is_archived: StrictBool


class CustomerCreate(CustomerBase):
    """Accept customer details without a client-supplied identifier."""


class CustomerUpdate(SQLModel):
    """Validate partial updates while distinguishing omitted fields from null.

    Only phone can explicitly be cleared. Names and email may be omitted but
    cannot be null when supplied. Unknown fields are rejected.
    """

    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("first_name", "last_name", "email")
    @classmethod
    def reject_null(cls, value: str | None) -> str:
        """Reject explicit null values while allowing omitted fields.

        Args:
            value: A supplied name or validated email value.

        Returns:
            The supplied non-null value.

        Raises:
            ValueError: If the supplied value is null.
        """
        if value is None:
            raise ValueError("This field cannot be null")
        return value

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Trim a supplied name and reject empty results.

        Args:
            value: The non-null first or last name.

        Returns:
            The name with surrounding whitespace removed.

        Raises:
            ValueError: If the name is empty after trimming.
        """
        value = value.strip()
        if not value:
            raise ValueError("Name must not be empty")
        return value
