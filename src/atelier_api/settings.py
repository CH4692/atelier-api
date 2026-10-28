"""Load shared application and migration settings from the environment."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, NoSuchModuleError


class Settings(BaseSettings):
    """Load DATABASE_URL from the environment, falling back to the local .env.

    Environment variables take precedence. Error messages omit input values
    because database URLs can contain credentials.
    """

    database_url: str
    # Accept the local test setting in the shared .env without using it at runtime.
    test_database_url: str | None = Field(default=None, repr=False)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Check URL syntax and dialect support without connecting.

        Args:
            value: The configured SQLAlchemy database URL.

        Returns:
            The unchanged URL, including any percent-encoded credentials.

        Raises:
            ValueError: If parsing fails, the dialect is unknown, or a
                PostgreSQL URL omits its database name.
        """
        try:
            url = make_url(value)
            url.get_dialect()
            if url.get_backend_name() == "postgresql" and not url.database:
                raise ValueError
        except ArgumentError, NoSuchModuleError, ValueError:
            raise ValueError(
                "DATABASE_URL must be a valid SQLAlchemy database URL; "
                "for PostgreSQL include a database name."
            ) from None
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        hide_input_in_errors=True,
    )


settings = Settings()
