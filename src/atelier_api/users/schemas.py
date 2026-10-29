"""Validate account details and keep credentials out of public user records."""

from datetime import UTC, datetime

from pydantic import EmailStr, SecretStr, field_validator
from sqlalchemy import String, true
from sqlmodel import Field, SQLModel

from .roles import UserRole


class UserBase(SQLModel):
    """Share normalized account email and activation state."""

    model_config = {"extra": "forbid", "hide_input_in_errors": True}

    email: EmailStr = Field(max_length=320, sa_type=String(320))
    is_active: bool = Field(default=True, sa_column_kwargs={"server_default": true()})

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize the complete email to lowercase for account uniqueness."""
        return value.lower()


class UserCreate(UserBase):
    """Accept a plaintext password only as a masked input value.

    Passwords contain 12 to 1024 characters and are never trimmed or truncated.
    Hashing is performed by the account service before database storage.
    """

    password: SecretStr = Field(min_length=12, max_length=1024, exclude=True)


class UserRead(UserBase):
    """Expose account identity and state without a password or its hash."""

    id: int
    role: UserRole
    customer_id: int | None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Expose database timestamps as timezone-aware UTC values."""
        if value.tzinfo is None:
            raise ValueError("Account timestamps must include a timezone")
        return value.astimezone(UTC)
