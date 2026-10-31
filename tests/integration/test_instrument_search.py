"""Verify actual SQL search, owner filters, stable pages and sorting on PostgreSQL."""

import pytest
from sqlalchemy import text

from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 200), ("admin", 200)]
)
def test_search_keeps_workshop_authorization(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        sign_in(client, role)
    assert (
        client.get(
            "/api/v1/instruments",
            params={"customer_id": 1, "q": "VIN", "sort_by": "maker"},
        ).status_code
        == expected
    )


@pytest.fixture
def searchable_instruments(postgres_client):
    owners = []
    for name in ("First", "Second"):
        response = postgres_client.post(
            "/api/v1/customers", json={"first_name": name, "last_name": "Owner"}
        )
        assert response.status_code == 201
        owners.append(response.json()["id"])
    records = []
    for kind, owner, category, identification, maker, year in [
        ("violin", owners[0], "customer", "VIN-001", "Alpha", 2000),
        ("violin", owners[1], "customer", "VIN-002", "Alpha", None),
        ("bow", None, "workshop", "50%_BOW", "Beta", 1990),
        ("cello", None, "unassigned", None, None, None),
        ("violin", owners[0], "customer", "VIN-003", "Alpha", 2005),
    ]:
        response = postgres_client.post(
            "/api/v1/instruments",
            json={
                "type": kind,
                "customer_id": owner,
                "ownership": category,
                "identification_number": identification,
                "maker": maker,
                "year_of_manufacture": year,
            },
        )
        assert response.status_code == 201
        records.append(response.json())
    return records, owners


@pytest.mark.parametrize(
    "query,indices",
    [
        (" vIn- ", [0, 1, 4]),
        ("001", [0]),
        ("%", [2]),
        ("_", [2]),
        ("50%_", [2]),
        ("' OR 1=1 --", []),
        ("missing", []),
        (" \t", [0, 1, 2, 3, 4]),
    ],
)
def test_identification_number_search(
    postgres_client, searchable_instruments, query, indices
):
    records, _ = searchable_instruments
    response = postgres_client.get("/api/v1/instruments", params={"q": query})
    assert response.status_code == 200
    assert response.json() == [records[index] for index in indices]
    assert int(response.headers["X-Total-Count"]) == len(indices)


@pytest.mark.parametrize(
    "parameters,indices",
    [
        ({"type": "violin"}, [0, 1, 4]),
        ({"ownership": "workshop"}, [2]),
        ({"type": "cello", "ownership": "unassigned"}, [3]),
        ({"customer_id": "first"}, [0, 4]),
        ({"customer_id": "second", "type": "violin"}, [1]),
        (
            {
                "customer_id": "first",
                "type": "violin",
                "ownership": "customer",
                "q": "003",
            },
            [4],
        ),
        ({"customer_id": "first", "ownership": "workshop"}, []),
        ({"customer_id": 999999}, []),
    ],
)
def test_owner_type_and_category_filters(
    postgres_client, searchable_instruments, parameters, indices
):
    records, owners = searchable_instruments
    parameters = dict(parameters)
    if parameters.get("customer_id") in ("first", "second"):
        parameters["customer_id"] = owners[
            0 if parameters["customer_id"] == "first" else 1
        ]
    response = postgres_client.get("/api/v1/instruments", params=parameters)
    assert response.status_code == 200
    assert response.json() == [records[index] for index in indices]
    assert int(response.headers["X-Total-Count"]) == len(indices)


@pytest.mark.parametrize(
    "offset,limit,indices",
    [(0, 2, [0, 1]), (2, 2, [4]), (3, 2, []), (1000, 1, []), (0, 200, [0, 1, 4])],
)
def test_filtered_pagination_boundaries(
    postgres_client, searchable_instruments, offset, limit, indices
):
    records, _ = searchable_instruments
    response = postgres_client.get(
        "/api/v1/instruments", params={"q": "VIN", "offset": offset, "limit": limit}
    )
    assert response.json() == [records[index] for index in indices]
    assert response.headers["X-Total-Count"] == "3"


@pytest.mark.parametrize(
    "field,direction,indices",
    [
        ("id", "desc", [4, 3, 2, 1, 0]),
        ("maker", "asc", [0, 1, 4, 2, 3]),
        ("maker", "desc", [2, 0, 1, 4, 3]),
        ("year_of_manufacture", "asc", [2, 0, 4, 1, 3]),
        ("year_of_manufacture", "desc", [4, 0, 2, 1, 3]),
        ("identification_number", "asc", [2, 0, 1, 4, 3]),
    ],
)
def test_sorting_resolves_ties_and_puts_nulls_last(
    postgres_client, searchable_instruments, field, direction, indices
):
    records, _ = searchable_instruments
    observed = []
    for offset in range(0, len(records), 2):
        response = postgres_client.get(
            "/api/v1/instruments",
            params={
                "sort_by": field,
                "sort_order": direction,
                "limit": 2,
                "offset": offset,
            },
        )
        assert response.status_code == 200
        assert response.headers["X-Total-Count"] == "5"
        observed.extend(response.json())
    assert observed == [records[index] for index in indices]
    assert len({record["id"] for record in observed}) == 5


def test_default_and_maximum_page_sizes_are_enforced_by_sql(
    postgres_client, db_connection
):
    db_connection.execute(
        text(
            "INSERT INTO instrument (type, ownership, identification_number) SELECT 'violin', 'unassigned', 'BULK-' || value::text FROM generate_series(1,201) AS series(value)"
        )
    )
    first = postgres_client.get("/api/v1/instruments")
    maximum = postgres_client.get("/api/v1/instruments", params={"limit": 200})
    last = postgres_client.get(
        "/api/v1/instruments", params={"limit": 200, "offset": 200}
    )
    for response in (first, maximum, last):
        assert response.status_code == 200
        assert response.headers["X-Total-Count"] == "201"
    assert (
        len(first.json()) == 100
        and len(maximum.json()) == 200
        and len(last.json()) == 1
    )
    assert first.json() == maximum.json()[:100]
    assert len({record["id"] for record in maximum.json() + last.json()}) == 201


def test_archive_does_not_hide_current_owner_instruments(
    postgres_client, searchable_instruments
):
    records, owners = searchable_instruments
    assert (
        postgres_client.patch(
            f"/api/v1/customers/{owners[0]}/archive", json={"is_archived": True}
        ).status_code
        == 200
    )
    response = postgres_client.get(
        "/api/v1/instruments", params={"customer_id": owners[0]}
    )
    assert response.json() == [records[0], records[4]]


def test_empty_database_returns_zero_total(postgres_client):
    response = postgres_client.get("/api/v1/instruments")
    assert response.status_code == 200 and response.json() == []
    assert response.headers["X-Total-Count"] == "0"
