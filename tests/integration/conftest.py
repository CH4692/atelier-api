"""PostgreSQL tests use a dedicated database and a disposable migrated schema."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine

from atelier_api.auth.dependencies import require_internal_user
from atelier_api.database import get_session
from atelier_api.main import app


@pytest.fixture(scope="session")
def postgres_engine():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith(
        "_test"
    ):
        pytest.fail(
            "TEST_DATABASE_URL must point to a PostgreSQL database ending in _test"
        )

    # Each run starts with an empty schema, including its own Alembic version table.
    schema = f"integration_{uuid4().hex}"
    admin_engine = create_engine(url)
    engine = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        options = f"{url.query.get('options', '')} -csearch_path={schema}".strip()
        scoped_url = url.update_query_dict({"options": options})
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[2],
            env={
                **os.environ,
                "DATABASE_URL": scoped_url.render_as_string(hide_password=False),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if result.returncode:
            pytest.fail(
                f"Integration database migration failed:\n{result.stdout}\n{result.stderr}"
            )
        engine = create_engine(scoped_url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.fixture
def db_connection(postgres_engine):
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
    # Verify cleanup even when an API handler explicitly committed its session.
    with postgres_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM customer")) == 0
        assert connection.scalar(text("SELECT count(*) FROM instrument")) == 0
        assert connection.scalar(text("SELECT count(*) FROM app_user")) == 0
        assert connection.scalar(text("SELECT count(*) FROM user_session")) == 0
        assert connection.scalar(text("SELECT count(*) FROM login_rate_limit")) == 0
        assert (
            connection.scalar(
                text(
                    "SELECT bootstrap_completed FROM user_provisioning_state WHERE id=1"
                )
            )
            is False
        )


@pytest.fixture
def postgres_client(db_connection):
    def session_override():
        # New session per request; commits release a savepoint, not the outer transaction.
        with Session(
            bind=db_connection, join_transaction_mode="create_savepoint"
        ) as session:
            yield session

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[require_internal_user] = lambda: None
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
