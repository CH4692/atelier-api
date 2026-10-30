"""Verify reversible customer archival, filtering and audit attribution."""

from unittest.mock import patch

import pytest

from atelier_api.customers.models import Customer


@pytest.fixture
def archive_target(mock_session):
    customer = Customer(
        id=8, first_name="Maria", last_name="Doe", email="maria@example.com"
    )
    mock_session.exec.return_value.first.return_value = customer
    mock_session.info = {"audit_actor_id": 4}
    return customer


@pytest.mark.parametrize(
    "archived,action", [(True, "customer.archived"), (False, "customer.restored")]
)
def test_archive_and_restore_keep_record_and_audit_actor(
    client, mock_session, archive_target, archived, action
):
    archive_target.is_archived = not archived
    before = archive_target.model_dump()
    response = client.patch(
        "/api/v1/customers/8/archive", json={"is_archived": archived}
    )
    assert response.status_code == 200
    assert response.json() == {**before, "is_archived": archived}
    params = mock_session.execute.call_args.args[0].compile().params
    assert params["action"] == action
    assert params["actor_id"] == 4
    assert params["resource_id"] == 8
    mock_session.delete.assert_not_called()
    mock_session.commit.assert_called_once()


def test_archive_repeat_does_not_write_audit(client, mock_session, archive_target):
    response = client.patch("/api/v1/customers/8/archive", json={"is_archived": False})
    assert response.status_code == 200
    mock_session.commit.assert_not_called()
    mock_session.execute.assert_not_called()


def test_archive_unknown_customer_returns_404(client, mock_session):
    mock_session.exec.return_value.first.return_value = None
    assert (
        client.patch(
            "/api/v1/customers/999/archive", json={"is_archived": True}
        ).status_code
        == 404
    )
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"is_archived": None},
        {"is_archived": "yes"},
        {"is_archived": 1},
        {"is_archived": True, "email": "private@example.com"},
    ],
)
def test_archive_rejects_invalid_payload(client, mock_session, payload):
    assert client.patch("/api/v1/customers/8/archive", json=payload).status_code == 422
    mock_session.exec.assert_not_called()


@pytest.mark.parametrize("include_archived", [False, True])
def test_search_and_count_use_same_archive_filter(
    client, mock_session, include_archived
):
    mock_session.exec.return_value.one.return_value = 0
    mock_session.exec.return_value.all.return_value = []
    response = client.get(
        "/api/v1/customers",
        params={"q": "Maria", "include_archived": str(include_archived).lower()},
    )
    assert response.status_code == 200
    for call in mock_session.exec.call_args_list:
        sql = str(call.args[0].compile())
        assert ("customer.is_archived IS false" in sql) is (not include_archived)


def test_failed_archive_audit_does_not_commit(client, mock_session, archive_target):
    with (
        patch(
            "atelier_api.customers.router.record_event",
            side_effect=RuntimeError("Audit failed"),
        ),
        pytest.raises(RuntimeError, match="Audit failed"),
    ):
        client.patch("/api/v1/customers/8/archive", json={"is_archived": True})
    mock_session.commit.assert_not_called()
