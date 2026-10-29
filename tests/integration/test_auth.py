"""Exercise real session persistence, browser security and account revocation."""

from datetime import timedelta
from hashlib import sha256
from secrets import token_urlsafe

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from atelier_api.auth.models import LoginRateLimit, UserSession
from atelier_api.auth.service import cleanup_expired_sessions, utc_now
from atelier_api.customers.models import Customer
from atelier_api.database import get_session
from atelier_api.main import create_app
from atelier_api.settings import Settings
from atelier_api.users.models import User
from atelier_api.users.passwords import hash_password
from atelier_api.users.roles import UserRole

ORIGIN = "https://app.example.test"
PASSWORD = "Workshop-test-password!42"
HEADERS = {"Origin": ORIGIN, "X-CSRF-Protection": "1"}


@pytest.fixture(scope="module")
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
        config = Settings(
            _env_file=None,
            database_url="sqlite://",
            environment="production",
            frontend_origins=[ORIGIN],
            **changes,
        )
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


def sign_in(client, name="employee", password=PASSWORD):
    return client.post(
        "/auth/login",
        json={"email": f"{name}@example.com", "password": password},
    )


def session_record(db_connection):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        return session.exec(select(UserSession)).one()


@pytest.mark.parametrize("name", ["admin", "employee"])
def test_login_cookie_and_authenticated_account(auth_factory, db_connection, name):
    client = auth_factory()
    response = sign_in(client, name)
    assert response.status_code == 200
    assert response.json()["role"] == name
    cookie = response.headers["set-cookie"]
    for attribute in [
        "__Host-session=",
        "HttpOnly",
        "Secure",
        "SameSite=lax",
        "Path=/",
        "Max-Age=28800",
    ]:
        assert attribute in cookie
    assert "domain=" not in cookie.lower()
    token = client.cookies.get("__Host-session")
    assert token and len(token) == 43
    record = session_record(db_connection)
    assert record.token_hash == sha256(token.encode()).hexdigest()
    assert token not in repr(record)
    assert token not in response.text
    assert "password" not in response.text
    assert "token_hash" not in response.text
    assert record.created_at.tzinfo is not None
    assert record.expires_at - record.created_at == timedelta(hours=8)
    assert client.get("/auth/me").json() == response.json()
    assert client.get("/customers").status_code == 200
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "email,password",
    [
        ("unknown@example.com", PASSWORD),
        ("not-an-email", PASSWORD),
        ("employee@example.com", "incorrect"),
        ("inactive@example.com", PASSWORD),
        ("customer@example.com", PASSWORD),
    ],
)
def test_generic_login_failures(auth_factory, email, password):
    response = auth_factory().post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert "set-cookie" not in response.headers


def test_case_insensitive_login(auth_factory):
    response = auth_factory().post(
        "/auth/login", json={"email": " EMPLOYEE@EXAMPLE.COM ", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "employee@example.com"


def test_customer_portal_does_not_grant_workshop_access(auth_factory):
    client = auth_factory(customer_portal_auth_enabled=True)
    assert sign_in(client, "customer").status_code == 200
    assert client.get("/auth/me").json()["role"] == "customer"
    for path in ["/customers", "/instruments", "/customers/1/instruments"]:
        assert client.get(path).status_code == 403


@pytest.mark.parametrize("cookie", [None, "invalid", token_urlsafe(32)])
def test_missing_and_invalid_sessions(auth_factory, cookie):
    client = auth_factory()
    if cookie:
        client.cookies.set("__Host-session", cookie)
    assert client.get("/auth/me").status_code == 401
    assert client.get("/instruments").status_code == 401
    assert client.get("/health/live").status_code == 200


@pytest.mark.parametrize("state", ["idle", "absolute", "revoked"])
def test_server_side_expiration(auth_factory, db_connection, state):
    client = auth_factory()
    assert sign_in(client).status_code == 200
    now = utc_now()
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        record = session.exec(select(UserSession)).one()
        if state == "idle":
            record.last_activity_at = now - timedelta(minutes=31)
        elif state == "absolute":
            record.created_at = now - timedelta(hours=9)
            record.expires_at = now - timedelta(seconds=1)
        else:
            record.revoked_at = now
        session.add(record)
        session.commit()
    assert client.get("/auth/me").status_code == 401


def test_activity_updates_idle_but_not_absolute_expiration(auth_factory, db_connection):
    client = auth_factory()
    sign_in(client)
    old = session_record(db_connection)
    assert client.get("/auth/me").status_code == 200
    current = session_record(db_connection)
    assert current.last_activity_at > old.last_activity_at
    assert current.expires_at == old.expires_at


def test_rotation_and_logout_prevent_replay(auth_factory, db_connection):
    client = auth_factory()
    sign_in(client)
    first = client.cookies.get("__Host-session")
    sign_in(client)
    second = client.cookies.get("__Host-session")
    assert first != second
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        records = session.exec(select(UserSession)).all()
        assert len(records) == 2
        assert sum(row.revoked_at is not None for row in records) == 1
    response = client.post("/auth/logout")
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert "Max-Age=0" in cookie and "Secure" in cookie and "HttpOnly" in cookie
    assert "Domain=" not in cookie
    assert client.post("/auth/logout").status_code == 204
    for token in [first, second]:
        client.cookies.set("__Host-session", token)
        assert client.get("/auth/me").status_code == 401


@pytest.mark.parametrize("change", ["deactivate", "role", "password"])
def test_account_security_changes_revoke_sessions(
    auth_factory, db_connection, accounts, password_hash, change
):
    client = auth_factory()
    sign_in(client)
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        user = session.get(User, accounts["employee"])
        if change == "deactivate":
            user.is_active = False
        elif change == "role":
            user.role = UserRole.ADMIN
        else:
            user.hashed_password = hash_password("Changed-password!123")
        session.add(user)
        session.commit()
    assert session_record(db_connection).revoked_at is not None
    assert client.get("/auth/me").status_code == 401
    if change == "deactivate":
        db_connection.execute(
            text(
                "UPDATE app_user SET is_active=true WHERE email='employee@example.com'"
            )
        )
        assert client.get("/auth/me").status_code == 401


@pytest.mark.parametrize(
    "path", ["/auth/login", "/auth/logout", "/customers", "/instruments"]
)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": ORIGIN},
        {"X-CSRF-Protection": "1"},
        {"Origin": "https://evil.example.test", "X-CSRF-Protection": "1"},
        {"Origin": "null", "X-CSRF-Protection": "1"},
        {"Origin": ORIGIN, "X-CSRF-Protection": "wrong"},
    ],
)
def test_unsafe_requests_require_origin_and_custom_header(auth_factory, path, headers):
    client = auth_factory()
    sign_in(client)
    client.headers.clear()
    response = client.post(
        path,
        headers=headers,
        json={
            "email": "employee@example.com",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 403


def test_cors_allows_only_exact_credentialed_origins(auth_factory):
    client = auth_factory()
    headers = {
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-csrf-protection",
    }
    response = client.options("/auth/login", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    headers["Origin"] = "https://evil.example.test"
    response = client.options("/auth/login", headers=headers)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_production_rejects_http(auth_factory):
    client = auth_factory()
    response = client.post(
        "http://api.example.test/auth/login",
        json={
            "email": "employee@example.com",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


def test_account_rate_limit_is_shared_between_app_instances(auth_factory):
    client = auth_factory(login_account_limit=2)
    assert sign_in(client, password="wrong").status_code == 401
    assert sign_in(client, password="wrong").status_code == 401
    other = auth_factory(login_account_limit=2)
    response = sign_in(other)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_ip_throttling_ignores_untrusted_forwarded_headers(auth_factory):
    client = auth_factory(login_ip_limit=2)
    for index in range(3):
        response = client.post(
            "/auth/login",
            headers={"X-Forwarded-For": f"192.0.2.{index}"},
            json={
                "email": f"unknown{index}@example.com",
                "password": "wrong",
            },
        )
        assert response.status_code == (401 if index < 2 else 429)


def test_rate_window_resets_and_cleanup_removes_revoked_sessions(
    auth_factory, db_connection
):
    client = auth_factory(login_account_limit=1)
    sign_in(client)
    assert sign_in(client).status_code == 429
    db_connection.execute(
        text("UPDATE login_rate_limit SET window_started_at=now()-interval '1 hour'")
    )
    assert sign_in(client).status_code == 200
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        count = cleanup_expired_sessions(session, client.app.state.settings)
        assert count == 1
        assert len(session.exec(select(UserSession)).all()) == 1
        assert len(session.exec(select(LoginRateLimit)).all()) == 2


def test_credentials_and_tokens_are_absent_from_logs_and_errors(auth_factory, caplog):
    client = auth_factory()
    sign_in(client, password="secret-sentinel-value")
    sign_in(client)
    token = client.cookies.get("__Host-session")
    assert "secret-sentinel-value" not in caplog.text
    assert PASSWORD not in caplog.text
    assert token not in caplog.text
    response = client.post("/auth/login", json={"email": [], "password": PASSWORD})
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert response.json() == {"detail": "Invalid request"}
