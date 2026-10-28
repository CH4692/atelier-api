from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError

from atelier_api.main import app


@pytest.mark.parametrize("path", ["/customers", "/instruments"])
@pytest.mark.parametrize("error_type", [OperationalError, InterfaceError, TimeoutError])
def test_database_failure_returns_503_without_credentials(error_type, path):
    error = (
        error_type("SELECT private_password", {}, Exception("private_password"))
        if error_type is not TimeoutError
        else TimeoutError("private_password")
    )
    session = MagicMock()
    session.exec.side_effect = error
    with patch("atelier_api.database.Session") as session_class:
        session_class.return_value.__enter__.return_value = session
        response = TestClient(app).get(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "private_password" not in response.text
