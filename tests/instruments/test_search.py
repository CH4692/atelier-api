"""Verify validated search queries, safe sorting and bounded pagination."""

import pytest
from sqlalchemy.dialects import postgresql

from atelier_api.instruments.schemas import InstrumentSortField
from atelier_api.main import app


@pytest.mark.parametrize(
    "parameters",
    [
        {"q": "a" * 201},
        {"customer_id": 0},
        {"customer_id": -1},
        {"customer_id": "invalid"},
        {"offset": -1},
        {"offset": "1.5"},
        {"limit": 0},
        {"limit": 201},
        {"limit": "invalid"},
        {"sort_by": "id; DROP TABLE instrument"},
        {"sort_order": "DESC"},
        {"type": "invalid"},
        {"ownership": "invalid"},
    ],
)
def test_invalid_search_parameters_return_422(client, mock_session, parameters):
    assert client.get("/api/v1/instruments", params=parameters).status_code == 422
    mock_session.exec.assert_not_called()


def test_search_combines_filters_and_counts_before_pagination(client, mock_session):
    mock_session.exec.return_value.one.return_value = 17
    mock_session.exec.return_value.all.return_value = []
    response = client.get(
        "/api/v1/instruments",
        params={
            "q": "  50%_off  ",
            "customer_id": 7,
            "type": "bow",
            "ownership": "customer",
            "offset": 17,
            "limit": 1,
        },
    )
    assert response.status_code == 200 and response.json() == []
    assert response.headers["X-Total-Count"] == "17"
    count, page = [call.args[0] for call in mock_session.exec.call_args_list]
    for query in (count, page):
        compiled = query.compile(dialect=postgresql.dialect())
        assert {"50/%/_off", 7, "bow", "customer"} <= set(compiled.params.values())
        sql = str(compiled)
        assert "ILIKE" in sql and "50%_off" not in sql
    count_sql = str(count)
    assert "count(*)" in count_sql
    assert (
        "LIMIT" not in count_sql
        and "OFFSET" not in count_sql
        and "ORDER BY" not in count_sql
    )
    mock_session.get.assert_not_called()


@pytest.mark.parametrize("field", list(InstrumentSortField))
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_sorting_is_whitelisted_and_stable(client, mock_session, field, direction):
    mock_session.exec.return_value.one.return_value = 0
    mock_session.exec.return_value.all.return_value = []
    response = client.get(
        "/api/v1/instruments", params={"sort_by": field.value, "sort_order": direction}
    )
    assert response.status_code == 200
    query = mock_session.exec.call_args.args[0]
    sql = str(
        query.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    expected = f"ORDER BY instrument.{field.value} {direction.upper()} NULLS LAST"
    if field != InstrumentSortField.ID:
        expected += ", instrument.id ASC"
    assert expected in sql


@pytest.mark.parametrize("limit", [1, 200])
def test_page_size_boundaries_and_empty_total(client, mock_session, limit):
    mock_session.exec.return_value.one.return_value = 0
    mock_session.exec.return_value.all.return_value = []
    response = client.get("/api/v1/instruments", params={"limit": limit})
    assert response.status_code == 200 and response.json() == []
    assert response.headers["X-Total-Count"] == "0"


def test_default_pagination_and_sort(client, mock_session):
    mock_session.exec.return_value.one.return_value = 0
    mock_session.exec.return_value.all.return_value = []
    assert client.get("/api/v1/instruments").status_code == 200
    query = mock_session.exec.call_args.args[0]
    sql = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "ORDER BY instrument.id ASC NULLS LAST" in sql
    assert "LIMIT 100 OFFSET 0" in sql


def test_pagination_header_is_documented_and_available_to_browsers():
    operation = app.openapi()["paths"]["/api/v1/instruments"]["get"]
    assert operation["responses"]["200"]["headers"]["X-Total-Count"]["schema"] == {
        "type": "integer",
        "minimum": 0,
    }
    cors = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )
    assert "X-Total-Count" in cors.kwargs["expose_headers"]
