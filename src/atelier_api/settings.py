from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, NoSuchModuleError


class Settings(BaseSettings):
    database_url: str

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        try:
            url = make_url(value)
            url.get_dialect()
            if url.get_backend_name() == "postgresql" and not url.database:
                raise ValueError
        except (ArgumentError, NoSuchModuleError, ValueError):
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
