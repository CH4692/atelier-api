"""Load shared application and migration settings from the environment."""

from ipaddress import ip_network
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
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

    environment: Literal["development", "production"] = "development"
    frontend_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    session_idle_seconds: int = Field(default=1800, gt=0)
    session_absolute_seconds: int = Field(default=28800, gt=0)
    login_account_limit: int = Field(default=10, gt=0)
    login_ip_limit: int = Field(default=30, gt=0)
    login_window_seconds: int = Field(default=900, gt=0)
    trusted_proxy_ips: list[str] = []
    customer_portal_auth_enabled: bool = False

    @property
    def api_documentation_enabled(self) -> bool:
        """Expose interactive API documentation only during development."""
        return self.environment == "development"

    @property
    def session_cookie_name(self) -> str:
        """Keep production cookies host-bound and distinct from HTTP development."""
        return "__Host-session" if self.environment == "production" else "dev-session"

    @property
    def secure_cookies(self) -> bool:
        """Prevent configuration from disabling production cookie transport security."""
        return self.environment == "production"

    @field_validator("frontend_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        """Allow explicit HTTP(S) origins only, without wildcard or path matching."""
        if not values:
            raise ValueError("At least one frontend origin is required")
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in value
                or value != f"{parsed.scheme}://{parsed.netloc}"
            ):
                raise ValueError(
                    "Frontend origins must be explicit HTTP(S) origins without paths"
                )
        return values

    @field_validator("trusted_proxy_ips")
    @classmethod
    def validate_proxies(cls, values: list[str]) -> list[str]:
        """Trust forwarded client addresses only from explicitly configured networks."""
        for value in values:
            ip_network(value, strict=False)
        return values

    @model_validator(mode="after")
    def validate_security(self) -> Settings:
        """Reject production origins that would require insecure cookies."""
        if self.environment == "production" and any(
            not origin.startswith("https://") for origin in self.frontend_origins
        ):
            raise ValueError("Production frontend origins must use HTTPS")
        if self.session_absolute_seconds < self.session_idle_seconds:
            raise ValueError(
                "Absolute session lifetime must not be shorter than inactivity timeout"
            )
        return self

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
