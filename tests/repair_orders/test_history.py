"""Validate bounded history queries and the controlled field-name allowlist."""

import pytest
from pydantic import ValidationError

from atelier_api.audit.schemas import AuditDetails
from atelier_api.auth.dependencies import get_current_user
from atelier_api.main import app
from atelier_api.users.models import User
from atelier_api.users.roles import UserRole


@pytest.fixture
def history_admin(client, mock_session):
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="admin@example.com", hashed_password="unused", role=UserRole.ADMIN
    )
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


@pytest.mark.parametrize(
    "params", [{"offset": -1}, {"offset": "0.5"}, {"limit": 0}, {"limit": 201}]
)
def test_history_rejects_invalid_pagination(history_admin, mock_session, params):
    assert (
        history_admin.get("/api/v1/repairs/1/history", params=params).status_code == 422
    )
    mock_session.get.assert_not_called()
    mock_session.exec.assert_not_called()


def test_missing_repair_returns_404(history_admin, mock_session):
    mock_session.get.return_value = None
    assert history_admin.get("/api/v1/repairs/999/history").status_code == 404
    mock_session.exec.assert_not_called()


@pytest.mark.parametrize(
    "field", ["password", "hashed_password", "session_token", "token_hash"]
)
def test_history_field_names_cannot_embed_sensitive_data(field):
    with pytest.raises(ValidationError):
        AuditDetails.model_validate({"changed_fields": [field]})
