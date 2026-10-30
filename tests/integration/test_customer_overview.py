"""Verify overview isolation, relationship changes and backend access control."""

import pytest

from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration


def test_overview_excludes_other_customers_and_tracks_instrument_associations(
    postgres_client,
):
    customers = []
    for first in ("Maria", "Jon"):
        response = postgres_client.post(
            "/api/v1/customers",
            json={
                "first_name": first,
                "last_name": "Doe",
                "email": f"{first.lower()}@example.com",
            },
        )
        assert response.status_code == 201
        customers.append(response.json())
    first, second = customers
    instruments = []
    for owner in (first["id"], second["id"], None):
        response = postgres_client.post(
            "/api/v1/instruments", json={"type": "violin", "customer_id": owner}
        )
        assert response.status_code == 201
        instruments.append(response.json())
    path = f"/api/v1/customers/{first['id']}/overview"
    response = postgres_client.get(path)
    assert response.status_code == 200
    assert response.json() == {"customer": first, "instruments": [instruments[0]]}
    instrument_path = f"/api/v1/instruments/{instruments[0]['id']}"
    assert (
        postgres_client.patch(
            instrument_path, json={"customer_id": second["id"]}
        ).status_code
        == 200
    )
    assert postgres_client.get(path).json()["instruments"] == []
    archived = postgres_client.patch(
        f"/api/v1/customers/{first['id']}/archive", json={"is_archived": True}
    ).json()
    assert postgres_client.get(path).json()["customer"] == archived
    assert postgres_client.delete(f"/api/v1/customers/{first['id']}").status_code == 204
    assert postgres_client.get(path).status_code == 404


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
def test_customer_overview_requires_workshop_access(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        sign_in(client, role)
    assert client.get("/api/v1/customers/999999/overview").status_code == expected
