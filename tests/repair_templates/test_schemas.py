"""Reject invalid defaults and ambiguous template selection before database work."""

import pytest


@pytest.mark.parametrize(
    "change",
    [
        {"name": " "},
        {"name": "x" * 101},
        {"name": None},
        {"description": " "},
        {"description": "x" * 2001},
        {"description": None},
        {"default_unit_price": "-0.01"},
        {"default_unit_price": "1.001"},
        {"default_unit_price": "NaN"},
        {"default_unit_price": "Infinity"},
        {"default_unit_price": "10000000000"},
        {"customer_id": 1},
    ],
)
@pytest.mark.parametrize("method", ["post", "patch"])
def test_invalid_template_values_do_not_access_database(
    client, mock_session, change, method
):
    path = "/api/v1/repair-templates" + ("/1" if method == "patch" else "")
    response = getattr(client, method)(
        path, json={"name": "Bridge", "description": "Fit bridge", **change}
    )
    assert response.status_code == 422
    mock_session.execute.assert_not_called()
    mock_session.exec.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"template_id": 0},
        {"template_id": -1},
        {"template_unit_price": "1.00"},
        {"template_id": 1, "template_unit_price": "-0.01"},
        {"template_id": 1, "work_description": None},
    ],
)
def test_invalid_template_selection_is_rejected(client, mock_session, change):
    response = client.post(
        "/api/v1/repairs",
        json={
            "customer_id": 1,
            "instrument_id": 1,
            "work_description": "Work",
            **change,
        },
    )
    assert response.status_code == 422
    mock_session.execute.assert_not_called()
