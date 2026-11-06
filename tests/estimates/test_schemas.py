"""Reject invalid financial inputs and client-supplied approval identities."""

import pytest

BASE = "/api/v1/repairs/1/estimates"
LINE = {
    "kind": "service",
    "description": "Work",
    "quantity": "1",
    "unit_price": "10.00",
}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": []},
        {"items": [LINE] * 201},
        {"items": [{**LINE, "quantity": "0"}]},
        {"items": [{**LINE, "quantity": "0.0001"}]},
        {"items": [{**LINE, "unit_price": "0.001"}]},
        {"items": [{**LINE, "unit_price": "NaN"}]},
        {"items": [{**LINE, "kind": "invalid"}]},
        {"items": [{**LINE, "description": " "}]},
        {"items": [LINE], "status": "approved"},
        {"items": [LINE], "customer_id": 1},
    ],
)
@pytest.mark.parametrize("method,path", [("post", BASE), ("patch", BASE + "/1")])
def test_invalid_draft_input_returns_422(client, mock_session, payload, method, path):
    assert getattr(client, method)(path, json=payload).status_code == 422
    mock_session.execute.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"approved_at": "2026-11-01T10:00:00"},
        {"approved_at": None},
        {"approval_method": "unknown"},
        {"approval_recorded_by": 123},
        {"customer_id": 999},
        {"approval_reference": "x" * 501},
    ],
)
def test_approval_input_is_validated_before_database_access(
    client, mock_session, change
):
    payload = {
        "approved_at": "2026-11-01T10:00:00Z",
        "approval_method": "email",
        **change,
    }
    assert client.post(BASE + "/1/approval", json=payload).status_code == 422
    mock_session.execute.assert_not_called()


def test_approval_cannot_be_bypassed_with_status_patch(client, mock_session):
    assert (
        client.patch(BASE + "/1/status", json={"status": "approved"}).status_code == 422
    )
    mock_session.execute.assert_not_called()
