"""Accept login credentials without echoing them in validation errors."""

from pydantic import SecretStr
from sqlmodel import Field, SQLModel


class LoginRequest(SQLModel):
    """Validate the request shape; credential validity always produces generic 401."""

    model_config = {"extra": "forbid", "hide_input_in_errors": True}
    email: str = Field(max_length=320)
    password: SecretStr = Field(max_length=1024, exclude=True)
