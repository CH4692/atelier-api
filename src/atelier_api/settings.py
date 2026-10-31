"""Load shared application and migration settings from the environment."""

import re
from ipaddress import ip_network
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_core import PydanticCustomError
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
    public_qr_base_url: str | None = None
    r2_endpoint_url: str | None = Field(default=None, repr=False)
    r2_access_key_id: SecretStr | None = Field(default=None, repr=False)
    r2_secret_access_key: SecretStr | None = Field(default=None, repr=False)
    r2_bucket_name: str | None = None

    photo_soft_delete_retention_days: int = Field(default=30, ge=1, le=36500)
    photo_auto_purge_enabled: bool = False
    audit_retention_days: int = Field(default=180, ge=1)
    session_idle_seconds: int = Field(default=1800, gt=0)
    session_absolute_seconds: int = Field(default=28800, gt=0)
    login_account_limit: int = Field(default=10, gt=0)
    login_ip_limit: int = Field(default=30, gt=0)
    login_window_seconds: int = Field(default=900, gt=0)
    trusted_proxy_ips: list[str] = []
    customer_portal_auth_enabled: bool = False

    @field_validator("photo_soft_delete_retention_days", mode="before")
    @classmethod
    def validate_photo_retention_days(cls, value: object) -> object:
        """Reject booleans masquerading as day counts."""
        if isinstance(value, bool):
            raise PydanticCustomError(
                "photo_retention_days",
                "Photo retention days must be a positive integer",
            )
        return value

    @field_validator(
        "r2_endpoint_url",
        "r2_access_key_id",
        "r2_secret_access_key",
        "r2_bucket_name",
        mode="before",
    )
    @classmethod
    def empty_storage_value(cls, value: object) -> object:
        """Treat empty optional environment variables as unconfigured."""
        return None if value == "" else value

    @property
    def photo_storage_enabled(self) -> bool:
        """Enable photo storage only with a complete validated configuration."""
        return self.r2_endpoint_url is not None

    @model_validator(mode="after")
    def validate_photo_storage(self) -> Settings:
        """Keep storage optional, but reject partial or insecure configurations."""
        values = (
            self.r2_endpoint_url,
            self.r2_access_key_id,
            self.r2_secret_access_key,
            self.r2_bucket_name,
        )
        if all(value is None for value in values):
            return self
        if not all(values):
            raise ValueError("All four R2 configuration variables are required")
        endpoint = self.r2_endpoint_url or ""
        self.validate_origins([endpoint])
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.netloc.isascii()
            or any(ord(char) <= 32 or char in '\\<>"' for char in endpoint)
        ):
            raise ValueError("R2_ENDPOINT_URL must be an explicit HTTPS origin")
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("Invalid R2 endpoint port") from None
        if not re.fullmatch(
            r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.r2_bucket_name or ""
        ):
            raise ValueError("Invalid R2 bucket name")
        for secret in (self.r2_access_key_id, self.r2_secret_access_key):
            if secret is None or not secret.get_secret_value().strip():
                raise ValueError("R2 credentials cannot be blank")
        return self

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

    @field_validator("public_qr_base_url")
    @classmethod
    def validate_qr_base_url(cls, value: str | None) -> str | None:
        """Accept a bounded explicit origin, never a request-derived host."""
        if value is None:
            return None
        cls.validate_origins([value])
        parsed = urlsplit(value)
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("Invalid PUBLIC_QR_BASE_URL port") from None
        if (
            len(value) > 500
            or not parsed.netloc.isascii()
            or any(
                ord(char) <= 32 or ord(char) == 127 or char in '\\<>"' for char in value
            )
        ):
            raise ValueError("Invalid PUBLIC_QR_BASE_URL origin")
        return value

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
        if (
            self.environment == "production"
            and self.public_qr_base_url is not None
            and not self.public_qr_base_url.startswith("https://")
        ):
            raise ValueError("Production PUBLIC_QR_BASE_URL must use HTTPS")
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
