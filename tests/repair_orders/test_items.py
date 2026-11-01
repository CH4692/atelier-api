"""Verify the approved monetary rounding policy and bounded item inputs."""

from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from atelier_api.repair_orders.amounts import line_amount, sum_amounts


@pytest.mark.parametrize(
    "quantity,price,expected",
    [
        ("3", "0.10", "0.30"),
        ("0.333", "0.05", "0.02"),
        ("0.5", "0.01", "0.01"),
        ("0.499", "0.01", "0.00"),
        ("1", "0", "0.00"),
        ("999999.999", "9999999999.99", "9999999989990000.00"),
    ],
)
def test_line_amount_is_exact_and_independent_of_ambient_context(
    quantity, price, expected
):
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        result = line_amount(Decimal(quantity), Decimal(price))
    assert result == Decimal(expected)
    assert result.as_tuple().exponent == -2


def test_total_is_sum_of_rounded_lines_rather_than_rounded_raw_products():
    amounts = [line_amount(Decimal("0.5"), Decimal("0.01")) for _ in range(3)]
    assert sum_amounts(amounts) == Decimal("0.03")
    assert sum_amounts([]) == Decimal("0.00")


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "invalid"},
        {"kind": None},
        {"description": " "},
        {"description": "x" * 2001},
        {"description": None},
        {"quantity": "0"},
        {"quantity": "-1"},
        {"quantity": "1.0001"},
        {"quantity": "1000000"},
        {"quantity": "NaN"},
        {"quantity": "Infinity"},
        {"quantity": None},
        {"unit_price": "-0.01"},
        {"unit_price": "1.001"},
        {"unit_price": "10000000000"},
        {"unit_price": "NaN"},
        {"unit_price": "Infinity"},
        {"unit_price": None},
        {"repair_order_id": 2},
        {"line_total": "1.00"},
    ],
)
@pytest.mark.parametrize("method", ["post", "patch"])
def test_invalid_item_input_is_rejected_without_database_access(
    client, mock_session, change, method
):
    payload = {
        "kind": "service",
        "description": "Bridge work",
        "quantity": "1",
        "unit_price": "10.00",
        **change,
    }
    path = "/api/v1/repairs/1/items" + ("/1" if method == "patch" else "")
    assert getattr(client, method)(path, json=payload).status_code == 422
    mock_session.execute.assert_not_called()


@pytest.mark.parametrize("missing", ["kind", "description", "quantity", "unit_price"])
def test_item_creation_requires_all_fields(client, mock_session, missing):
    payload = {
        "kind": "service",
        "description": "Work",
        "quantity": "1",
        "unit_price": "10.00",
    }
    del payload[missing]
    assert client.post("/api/v1/repairs/1/items", json=payload).status_code == 422
    mock_session.execute.assert_not_called()
