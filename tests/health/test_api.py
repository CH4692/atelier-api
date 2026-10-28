from fastapi.testclient import TestClient

from atelier_api.main import app

client = TestClient(app)


def test_health_check_ready():
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_check_live():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_database_failure_returns_503():
    from unittest.mock import MagicMock

    from sqlalchemy.exc import SQLAlchemyError

    from atelier_api.database import get_session

    session = MagicMock()
    session.exec.side_effect = SQLAlchemyError("private_password")
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = lambda: session
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}
    assert "private_password" not in response.text
