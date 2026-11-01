"""Verify all state pairs and reject malformed status changes before database work."""

from itertools import product

import pytest

from atelier_api.repair_orders.statuses import RepairStatus, validate_transition

# Business expectations are independent of the implementation's transition map.
EXPECTED = {
    "accepted": {"awaiting_approval", "in_progress", "cancelled"},
    "awaiting_approval": {"in_progress", "cancelled"},
    "in_progress": {
        "awaiting_approval",
        "awaiting_materials",
        "ready_for_pickup",
        "cancelled",
    },
    "awaiting_materials": {"in_progress", "cancelled"},
    "ready_for_pickup": {"in_progress", "completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


@pytest.mark.parametrize("previous,target", list(product(RepairStatus, repeat=2)))
def test_all_repair_state_pairs(previous, target):
    if previous == target or target.value in EXPECTED[previous.value]:
        validate_transition(previous, target)
    else:
        with pytest.raises(ValueError, match="Cannot change repair status"):
            validate_transition(previous, target)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "invalid"},
        {"status": None},
        {"status": 1},
        {"status": "in_progress", "status_updated_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_status_payload_validation(client, mock_session, payload):
    assert client.patch("/api/v1/repairs/1/status", json=payload).status_code == 422
    mock_session.exec.assert_not_called()


def test_intake_rejects_client_controlled_status_timestamps(client, mock_session):
    response = client.post(
        "/api/v1/repairs",
        json={
            "customer_id": 1,
            "instrument_id": 1,
            "work_description": "Work",
            "status_updated_at": "2026-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422
    mock_session.exec.assert_not_called()
