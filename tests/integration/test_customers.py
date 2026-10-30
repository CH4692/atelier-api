import pytest
from sqlmodel import Session, select

from atelier_api.customers.models import Customer

pytestmark = pytest.mark.integration


@pytest.fixture
def searchable_customers(postgres_client):
    records = []
    for first, last, email, phone in (
        ("Maria", "Mueller", "maria@example.com", "+49 176 123456"),
        ("Jon", "Doe", "jon@example.org", None),
        ("Marie50%_off", "Doe", "discount@example.com", "+33123456789"),
    ):
        response = postgres_client.post(
            "/api/v1/customers",
            json={
                "first_name": first,
                "last_name": last,
                "email": email,
                "phone": phone,
            },
        )
        assert response.status_code == 201
        records.append(response.json())
    return records


@pytest.mark.parametrize(
    "query,indices",
    [
        ("mAR", [0, 2]),
        ("DOE", [1, 2]),
        ("RIA@EXAMPLE", [0]),
        ("176123", [0]),
        ("  MARIA MUELL  ", [0]),
        ("not-found", []),
        ("%", [2]),
        ("_", [2]),
        ("' OR 1=1 --", []),
        ("   ", [0, 1, 2]),
    ],
)
def test_search_customers(postgres_client, searchable_customers, query, indices):
    response = postgres_client.get("/api/v1/customers", params={"q": query})
    assert response.status_code == 200
    assert response.json() == [searchable_customers[index] for index in indices]
    assert int(response.headers["X-Total-Count"]) == len(indices)


@pytest.mark.parametrize("query,indices", [(None, [0, 1, 2]), ("doe", [1, 2])])
def test_search_customers_pagination(
    postgres_client, searchable_customers, query, indices
):
    pages = []
    for offset in range(len(indices) + 1):
        params = {"offset": offset, "limit": 1}
        if query is not None:
            params["q"] = query
        response = postgres_client.get("/api/v1/customers", params=params)
        assert response.status_code == 200
        assert int(response.headers["X-Total-Count"]) == len(indices)
        pages.append(response.json())
    assert pages == [[searchable_customers[index]] for index in indices] + [[]]


@pytest.mark.parametrize(
    "offset,limit,indices",
    [(0, 200, [0, 1, 2]), (0, 1, [0]), (2, 2, [2]), (3, 2, []), (1000, 1, [])],
)
def test_customer_pagination_boundaries(
    postgres_client, searchable_customers, offset, limit, indices
):
    response = postgres_client.get(
        "/api/v1/customers", params={"offset": offset, "limit": limit}
    )
    assert response.status_code == 200
    assert response.json() == [searchable_customers[index] for index in indices]
    assert response.headers["X-Total-Count"] == "3"


@pytest.mark.parametrize("phone", [None, "+49176123456789"])
def test_create_and_retrieve_customer(postgres_client, db_connection, phone):
    payload = {
        "first_name": "Maria",
        "last_name": "Müller",
        "email": "maria@example.com",
        "phone": phone,
    }
    response = postgres_client.post("/api/v1/customers", json=payload)
    assert response.status_code == 201
    created = response.json()
    assert isinstance(created["id"], int)
    assert created["id"] > 0
    assert created == {**payload, "id": created["id"], "is_archived": False}

    # This session shares no identity map with the session used by the POST request.
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Customer, created["id"])
        assert stored is not None
        assert stored.model_dump() == created

    response = postgres_client.get(f"/api/v1/customers/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created
    response = postgres_client.get("/api/v1/customers")
    assert response.status_code == 200
    assert response.json() == [created]


def test_customer_list_starts_empty(postgres_client):
    response = postgres_client.get("/api/v1/customers")
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["X-Total-Count"] == "0"


def test_committed_test_data_does_not_leak(postgres_client, db_connection):
    assert postgres_client.get("/api/v1/customers").json() == []
    for name in ("Jon", "Maria"):
        response = postgres_client.post(
            "/api/v1/customers",
            json={
                "first_name": name,
                "last_name": "Doe",
                "email": f"{name.lower()}@example.com",
            },
        )
        assert response.status_code == 201
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert len(session.exec(select(Customer)).all()) == 2


def test_missing_customer_returns_404(postgres_client):
    response = postgres_client.get("/api/v1/customers/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}


def test_invalid_customer_is_not_persisted(postgres_client):
    response = postgres_client.post(
        "/api/v1/customers",
        json={
            "first_name": "Jon",
            "last_name": "Doe",
            "email": "invalid",
        },
    )
    assert response.status_code == 422
    assert postgres_client.get("/api/v1/customers").json() == []


def test_delete_customer_removes_record_and_preserves_other_customers(
    postgres_client, db_connection
):
    created = []
    for name in ("Jon", "Maria"):
        response = postgres_client.post(
            "/api/v1/customers",
            json={
                "first_name": name,
                "last_name": "Doe",
                "email": f"{name.lower()}@example.com",
            },
        )
        assert response.status_code == 201
        created.append(response.json())
    deleted, retained = created
    path = f"/api/v1/customers/{deleted['id']}"

    response = postgres_client.delete(path)
    assert response.status_code == 204
    assert response.content == b""

    # A fresh session must observe the delete, independently of the API identity map.
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert session.get(Customer, deleted["id"]) is None
        assert session.get(Customer, retained["id"]) is not None

    response = postgres_client.get(path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    response = postgres_client.get("/api/v1/customers")
    assert response.status_code == 200
    assert response.json() == [retained]
    response = postgres_client.delete(path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    assert postgres_client.get("/api/v1/customers").json() == [retained]


def test_delete_unknown_customer_does_not_change_database(postgres_client):
    response = postgres_client.delete("/api/v1/customers/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    assert postgres_client.get("/api/v1/customers").json() == []


def test_customer_lifecycle_with_persisted_update(postgres_client, db_connection):
    payload = {
        "first_name": "Jon",
        "last_name": "Doe",
        "email": "jon@example.com",
        "phone": "+49176123456789",
    }
    response = postgres_client.post("/api/v1/customers", json=payload)
    assert response.status_code == 201
    created = response.json()
    path = f"/api/v1/customers/{created['id']}"
    response = postgres_client.get(path)
    assert response.status_code == 200
    assert response.json() == created

    response = postgres_client.patch(
        path, json={"first_name": "Maria", "email": "maria@example.com", "phone": None}
    )
    assert response.status_code == 200
    updated = {
        **created,
        "first_name": "Maria",
        "email": "maria@example.com",
        "phone": None,
    }
    assert response.json() == updated
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(Customer, created["id"])
        assert stored is not None
        assert stored.model_dump() == updated

    response = postgres_client.get(path)
    assert response.status_code == 200
    assert response.json() == updated
    response = postgres_client.get("/api/v1/customers")
    assert response.status_code == 200
    assert response.json() == [updated]

    response = postgres_client.patch(path, json={"email": "invalid"})
    assert response.status_code == 422
    assert postgres_client.get(path).json() == updated
    response = postgres_client.delete(path)
    assert response.status_code == 204
    assert response.content == b""
    assert postgres_client.get("/api/v1/customers").json() == []
    assert postgres_client.get(path).status_code == 404
    assert postgres_client.patch(path, json={"first_name": "Jon"}).status_code == 404
    assert postgres_client.delete(path).status_code == 404
