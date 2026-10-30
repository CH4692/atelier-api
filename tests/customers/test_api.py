import pytest

from atelier_api.customers.models import Customer
from atelier_api.customers.schemas import CustomerRead
from atelier_api.main import app

testdata_customers: list[Customer] = [
    Customer(
        id=1,
        first_name="Jon",
        last_name="Doe",
        email="jon.doe@example.com",
        phone="+49176123456789",
    ),
    Customer(
        id=2,
        first_name="Maria",
        last_name="Doe",
        email="maria.doe@example.de",
        phone="+49123456789",
    ),
]
test_customer = Customer(
    id=1,
    first_name="Jon",
    last_name="Doe",
    email="jon.doe@example.com",
    phone="+49176123456789",
)


def test_get_customers(client, mock_session):
    mock_session.exec.return_value.all.return_value = testdata_customers
    response = client.get("/api/v1/customers")
    assert response.status_code == 200
    expected_json = [
        CustomerRead.model_validate(c).model_dump() for c in testdata_customers
    ]
    assert response.json() == expected_json


def test_get_customer_by_id(client, mock_session):
    mock_session.get.return_value = test_customer
    response = client.get("/api/v1/customers/1")
    assert response.status_code == 200
    expected_json = CustomerRead.model_validate(test_customer).model_dump(mode="json")
    assert response.json() == expected_json
    mock_session.get.assert_called_once_with(Customer, 1)


def test_get_customer_by_id_not_found(client, mock_session):
    mock_session.get.return_value = None
    response = client.get("/api/v1/customers/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    mock_session.get.assert_called_once_with(Customer, 999)


def test_get_customer_by_id_invalid_id(client, mock_session):
    response = client.get("/api/v1/customers/abc")
    assert response.status_code == 422
    mock_session.get.assert_not_called()


@pytest.mark.parametrize(
    "customer_id",
    [0, -1, 999999],
)
def test_get_customer_by_id_not_found_for_boundary_values(
    client,
    mock_session,
    customer_id,
):
    mock_session.get.return_value = None
    response = client.get(f"/api/v1/customers/{customer_id}")
    assert response.status_code == 404
    mock_session.get.assert_called_once_with(
        Customer,
        customer_id,
    )


def test_create_customer(client, mock_session):
    payload = {
        "first_name": "Jon",
        "last_name": "Doe",
        "email": "jon.doe@example.com",
        "phone": "+49176123456789",
    }

    def refresh_customer(customer):
        customer.id = 1

    mock_session.refresh.side_effect = refresh_customer
    response = client.post("/api/v1/customers", json=payload)
    assert response.status_code == 201
    mock_session.add.assert_called_once()
    saved_customer = mock_session.add.call_args.args[0]
    assert isinstance(saved_customer, Customer)
    assert saved_customer.first_name == payload["first_name"]
    assert saved_customer.last_name == payload["last_name"]
    assert saved_customer.email == payload["email"]
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once_with(saved_customer)


def test_get_customers_empty(client, mock_session):
    mock_session.exec.return_value.all.return_value = []
    response = client.get("/api/v1/customers")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [
        {"offset": -1},
        {"offset": "invalid"},
        {"offset": "1.5"},
        {"limit": 0},
        {"limit": 201},
        {"limit": "invalid"},
        {"limit": "1.5"},
        {"q": "a" * 201},
    ],
)
def test_customer_search_rejects_invalid_parameters(client, mock_session, params):
    assert client.get("/api/v1/customers", params=params).status_code == 422
    mock_session.exec.assert_not_called()


def test_customer_search_uses_bound_literal_query_and_pagination(client, mock_session):
    from sqlalchemy.dialects import postgresql

    mock_session.exec.return_value.all.return_value = []
    response = client.get(
        "/api/v1/customers", params={"q": "  50%_off  ", "offset": 2, "limit": 3}
    )
    assert response.status_code == 200
    assert response.json() == []
    statement = mock_session.exec.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "ILIKE" in str(compiled)
    assert "ORDER BY customer.id" in str(compiled)
    assert "50%_off" not in str(compiled)
    assert list(compiled.params.values()).count("50/%/_off") == 5
    literal_sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "LIMIT 3 OFFSET 2" in literal_sql
    count_statement = mock_session.exec.call_args_list[0].args[0]
    count_sql = str(count_statement.compile(dialect=postgresql.dialect()))
    assert "count(*)" in count_sql
    assert "ILIKE" in count_sql
    assert "LIMIT" not in count_sql and "OFFSET" not in count_sql
    assert list(count_statement.compile().params.values()).count("50/%/_off") == 5


@pytest.mark.parametrize(
    "offset,limit", [(0, 1), (0, 200), (2, 2), (3, 100), (1000, 100)]
)
def test_customer_pagination_reports_total_on_empty_pages(
    client, mock_session, offset, limit
):
    mock_session.exec.return_value.one.return_value = 3
    mock_session.exec.return_value.all.return_value = []
    response = client.get(
        "/api/v1/customers", params={"offset": offset, "limit": limit}
    )
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["X-Total-Count"] == "3"


def test_customer_pagination_defaults_and_zero_total(client, mock_session):
    mock_session.exec.return_value.one.return_value = 0
    mock_session.exec.return_value.all.return_value = []
    response = client.get("/api/v1/customers")
    assert response.headers["X-Total-Count"] == "0"
    statement = mock_session.exec.call_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "ORDER BY customer.id" in sql
    assert "LIMIT 100 OFFSET 0" in sql


def test_customer_pagination_total_is_documented():
    operation = app.openapi()["paths"]["/api/v1/customers"]["get"]
    assert operation["responses"]["200"]["headers"]["X-Total-Count"]["schema"] == {
        "type": "integer",
        "minimum": 0,
    }


def test_customer_pagination_total_is_readable_by_browser(mock_session):
    from fastapi.testclient import TestClient

    from atelier_api.auth.dependencies import require_internal_user
    from atelier_api.database import get_session
    from atelier_api.main import create_app
    from atelier_api.settings import Settings

    application = create_app(
        Settings(
            _env_file=None,
            database_url="sqlite://",
            frontend_origins=["https://app.example.test"],
        )
    )
    application.dependency_overrides[get_session] = lambda: mock_session
    application.dependency_overrides[require_internal_user] = lambda: None
    mock_session.exec.return_value.one.return_value = 0
    mock_session.exec.return_value.all.return_value = []
    with TestClient(application) as browser:
        response = browser.get(
            "/api/v1/customers", headers={"Origin": "https://app.example.test"}
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.test"
    assert "x-total-count" in response.headers["access-control-expose-headers"].lower()
    assert response.headers["X-Total-Count"] == "0"


def test_create_customer_missing_required_fields(client, mock_session):
    response = client.post("/api/v1/customers", json={})
    assert response.status_code == 422
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


def test_create_customer_invalid_email(client, mock_session):
    payload = {
        "first_name": "Jon",
        "last_name": "Doe",
        "email": "keine-gueltige-email",
        "phone": "+49176123456789",
    }

    response = client.post("/api/v1/customers", json=payload)
    assert response.status_code == 422
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.fixture
def update_target(mock_session):
    # Use a new instance so updates cannot mutate shared test data.
    customer = Customer(
        id=1,
        first_name="Jon",
        last_name="Doe",
        email="jon.doe@example.com",
        phone="+49176123456789",
    )
    mock_session.get.return_value = customer
    return customer


def test_update_customer_all_fields(client, mock_session, update_target):
    payload = {
        "first_name": "Maria",
        "last_name": "Müller",
        "email": "maria@example.com",
        "phone": "+49123456789",
    }
    response = client.patch("/api/v1/customers/1", json=payload)
    assert response.status_code == 200
    assert response.json() == {"id": 1, **payload, "is_archived": False}
    mock_session.get.assert_called_once_with(Customer, 1)
    mock_session.add.assert_called_once_with(update_target)
    mock_session.commit.assert_called_once()
    mock_session.refresh.assert_called_once_with(update_target)


def test_update_customer_preserves_omitted_fields(client, mock_session, update_target):
    before = update_target.model_dump()
    response = client.patch("/api/v1/customers/1", json={"first_name": "  Maria  "})
    assert response.status_code == 200
    assert response.json() == {**before, "first_name": "Maria"}
    mock_session.commit.assert_called_once()


def test_update_customer_can_clear_phone(client, mock_session, update_target):
    response = client.patch("/api/v1/customers/1", json={"phone": None})
    assert response.status_code == 200
    assert response.json()["phone"] is None
    mock_session.commit.assert_called_once()


def test_update_customer_empty_body_is_noop(client, mock_session, update_target):
    response = client.patch("/api/v1/customers/1", json={})
    assert response.status_code == 200
    assert response.json() == update_target.model_dump()
    mock_session.commit.assert_not_called()


def test_update_customer_unknown_id(client, mock_session):
    mock_session.get.return_value = None
    response = client.patch("/api/v1/customers/999", json={"first_name": "Maria"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "invalid"},
        {"first_name": None},
        {"last_name": None},
        {"first_name": ""},
        {"last_name": "   "},
        {"first_name": 123},
        {"phone": 123},
        {"id": 2},
        {"unknown": "value"},
    ],
)
def test_update_customer_rejects_invalid_data(client, mock_session, payload):
    response = client.patch("/api/v1/customers/1", json=payload)
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.commit.assert_not_called()


def test_update_customer_rejects_invalid_id(client, mock_session):
    response = client.patch("/api/v1/customers/abc", json={"first_name": "Maria"})
    assert response.status_code == 422
    mock_session.get.assert_not_called()


def test_update_customer_requires_request_body(client, mock_session):
    response = client.patch("/api/v1/customers/1")
    assert response.status_code == 422
    mock_session.commit.assert_not_called()


def test_update_customer_documented_in_openapi():
    operation = app.openapi()["paths"]["/api/v1/customers/{customer_id}"]["patch"]
    assert operation["requestBody"]["required"] is True
    assert {"200", "404", "422"} <= operation["responses"].keys()
    assert operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/CustomerUpdate")


def test_delete_customer_returns_empty_204(client, mock_session, update_target):
    response = client.delete("/api/v1/customers/1")
    assert response.status_code == 204
    assert response.content == b""
    mock_session.get.assert_called_once_with(Customer, 1)
    mock_session.delete.assert_called_once_with(update_target)
    mock_session.commit.assert_called_once()


def test_delete_customer_unknown_id(client, mock_session):
    mock_session.get.return_value = None
    response = client.delete("/api/v1/customers/999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    mock_session.delete.assert_not_called()
    mock_session.commit.assert_not_called()


def test_delete_customer_invalid_id(client, mock_session):
    response = client.delete("/api/v1/customers/abc")
    assert response.status_code == 422
    mock_session.get.assert_not_called()
    mock_session.delete.assert_not_called()
    mock_session.commit.assert_not_called()


def test_delete_customer_documented_in_openapi():
    operation = app.openapi()["paths"]["/api/v1/customers/{customer_id}"]["delete"]
    assert {"204", "404", "422", "503"} <= operation["responses"].keys()
    assert "content" not in operation["responses"]["204"]
    assert "requestBody" not in operation
