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
from atelier_api.customers.models import Customer
from atelier_api.database import get_session
from atelier_api.main import app, create_app
from atelier_api.settings import Settings
from atelier_api.users.models import User
from atelier_api.users.passwords import hash_password
from atelier_api.users.roles import UserRole
from tests.database_helpers import worker_database
from tests.integration.auth_helpers import HEADERS, ORIGIN, PASSWORD


@pytest.fixture(scope="session")
def postgres_engine(worker_id):
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

    with worker_database(url, worker_id) as isolated_url:
        # Each run starts with an empty schema, including its own Alembic version table.
        schema = f"integration_{uuid4().hex}"
        admin_engine = create_engine(isolated_url, hide_parameters=True)
        engine = None
        try:
            with admin_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            options = f"{isolated_url.query.get('options', '')} -csearch_path={schema} -ctimezone=UTC".strip()
            scoped_url = isolated_url.update_query_dict({"options": options})
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
        counts = (
            connection.execute(
                text("""
            SELECT
              (SELECT count(*) FROM audit_event) AS audit_event,
              (SELECT count(*) FROM customer) AS customer,
              (SELECT count(*) FROM instrument) AS instrument,
              (SELECT count(*) FROM repair_order) AS repair_order,
              (SELECT count(*) FROM repair_document) AS repair_document,
              (SELECT count(*) FROM instrument_photo) AS instrument_photo,
              (SELECT count(*) FROM instrument_ownership_event) AS instrument_ownership_event,
              (SELECT count(*) FROM app_user) AS app_user,
              (SELECT count(*) FROM user_session) AS user_session,
              (SELECT count(*) FROM login_rate_limit) AS login_rate_limit,
              (SELECT bootstrap_completed FROM user_provisioning_state WHERE id=1) AS bootstrap_completed
        """)
            )
            .mappings()
            .one()
        )
        for table in (
            "audit_event",
            "customer",
            "instrument",
            "repair_order",
            "repair_document",
            "instrument_photo",
            "instrument_ownership_event",
            "app_user",
            "user_session",
            "login_rate_limit",
        ):
            assert counts[table] == 0, f"Test leaked rows into {table}"
        assert counts["bootstrap_completed"] is False


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


@pytest.fixture(scope="session")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def accounts(db_connection, password_hash):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        customer = Customer(
            first_name="Test", last_name="Owner", email="owner@example.com"
        )
        session.add(customer)
        session.flush()
        result = {}
        for name, role, active in [
            ("admin", UserRole.ADMIN, True),
            ("employee", UserRole.EMPLOYEE, True),
            ("inactive", UserRole.EMPLOYEE, False),
            ("customer", UserRole.CUSTOMER, True),
        ]:
            user = User(
                email=f"{name}@example.com",
                hashed_password=password_hash,
                role=role,
                is_active=active,
                customer_id=customer.id if role == UserRole.CUSTOMER else None,
            )
            session.add(user)
            session.flush()
            result[name] = user.id
        session.commit()
        return result


@pytest.fixture
def auth_factory(db_connection, accounts):
    clients = []

    def build(**changes):
        options = {"environment": "production", "frontend_origins": [ORIGIN]}
        options.update(changes)
        config = Settings(_env_file=None, database_url="sqlite://", **options)
        app = create_app(config)

        def override():
            with Session(
                bind=db_connection, join_transaction_mode="create_savepoint"
            ) as session:
                yield session

        app.dependency_overrides[get_session] = override
        client = TestClient(app, base_url="https://api.example.test", headers=HEADERS)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in reversed(clients):
        client.__exit__(None, None, None)
