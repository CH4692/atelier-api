import pytest
from pydantic import ValidationError

from atelier_api.settings import Settings


def test_database_url_from_environment_overrides_dotenv(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=sqlite:///local.db\n")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///environment.db")
    assert Settings(_env_file=dotenv).database_url == "sqlite:///environment.db"


def test_database_url_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=sqlite:///local.db\n")
    assert Settings(_env_file=dotenv).database_url == "sqlite:///local.db"


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="Field required"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "password-secret",
        "unknown://user:password-secret@host/db",
        "postgresql+psycopg://host",
        "postgresql+psycopg://host:invalid/db",
    ],
)
def test_invalid_database_url_is_rejected_without_exposing_input(url):
    with pytest.raises(ValidationError) as error:
        Settings(database_url=url, _env_file=None)
    assert "DATABASE_URL must be a valid SQLAlchemy database URL" in str(error.value)
    assert "password-secret" not in str(error.value)


def test_percent_encoded_password_is_preserved():
    url = "postgresql+psycopg://atelier:secret%40example%25@localhost/atelier"
    assert Settings(database_url=url, _env_file=None).database_url == url


def test_shared_dotenv_accepts_separate_test_url(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "DATABASE_URL=sqlite:///development.db\n"
        "TEST_DATABASE_URL=postgresql+psycopg://localhost/atelier_test\n"
    )
    settings = Settings(_env_file=dotenv)
    assert settings.database_url == "sqlite:///development.db"
    assert settings.test_database_url == "postgresql+psycopg://localhost/atelier_test"
    assert "atelier_test" not in repr(settings)
