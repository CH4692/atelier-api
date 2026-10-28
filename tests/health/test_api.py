from sqlalchemy.exc import SQLAlchemyError


def test_health_check_ready(client, mock_session):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
    mock_session.exec.assert_called_once()


def test_health_check_live(client, mock_session):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_session.exec.assert_not_called()


def test_readiness_database_failure_returns_503(client, mock_session):
    mock_session.exec.side_effect = SQLAlchemyError("private_password")
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}
    assert "private_password" not in response.text
