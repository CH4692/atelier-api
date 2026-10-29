from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import InstrumentType


@pytest.mark.parametrize(
    "method, path",
    [
        ("POST", "/instruments"),
        ("PATCH", "/instruments/1"),
    ],
)
@pytest.mark.parametrize("body", [b"[]", b"null", b'"not an object"'])
def test_instrument_writes_require_json_object(
    client, mock_session, method, path, body
):
    response = client.request(
        method, path, content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


def test_instrument_update_rejects_malformed_json(client, mock_session):
    response = client.patch(
        "/instruments/1",
        content=b"{invalid",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize(
    "method, payload",
    [
        ("POST", {"type": "violin"}),
        ("PATCH", {"notes": "Updated notes."}),
        ("DELETE", None),
    ],
)
def test_failed_instrument_commit_returns_503_instead_of_success(
    client, method, payload
):
    session = MagicMock()
    session.get.return_value = Instrument(id=1, type=InstrumentType.VIOLIN)
    session.commit.side_effect = OperationalError(
        "private_statement", {}, Exception("private_password")
    )
    path = "/instruments" if method == "POST" else "/instruments/1"
    # Keep the real session dependency to exercise its error translation.
    with patch("atelier_api.database.Session") as session_class:
        session_class.return_value.__enter__.return_value = session
        response = client.request(method, path, json=payload)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "private_password" not in response.text
    assert "private_statement" not in response.text
    session.commit.assert_called_once()
