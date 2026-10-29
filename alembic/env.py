"""Run online and offline migrations using the shared database settings."""

from logging.config import fileConfig

from alembic.util import CommandError
from sqlalchemy import create_engine, pool
from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError
from sqlmodel import SQLModel

from alembic import context
from atelier_api.audit.models import AuditEvent  # noqa: F401
from atelier_api.auth.models import LoginRateLimit, UserSession  # noqa: F401

# Register table models in SQLModel.metadata before Alembic inspects it.
from atelier_api.customers.models import Customer  # noqa: F401
from atelier_api.instruments.models import Instrument  # noqa: F401
from atelier_api.settings import settings
from atelier_api.users.models import User  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Emit migration SQL without opening a database connection."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations using the configured database URL.

    Raises:
        CommandError: If the connection fails, without exposing credentials.
    """
    connectable = create_engine(
        settings.database_url,
        poolclass=pool.NullPool,
    )

    try:
        try:
            connection = connectable.connect()
        except OperationalError, InterfaceError, TimeoutError:
            raise CommandError(
                "Database connection failed. Check DATABASE_URL and ensure "
                "PostgreSQL is running and accepts connections."
            ) from None
        with connection:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
