"""Check the fictional small profile independently of database access."""

from collections import Counter
from datetime import date
from decimal import Decimal
from itertools import pairwise

from atelier_api.demo.data import build_small
from atelier_api.repair_orders.statuses import RepairStatus, validate_transition


def test_small_profile_is_repeatable_and_covers_valid_workshop_scenarios():
    plan = build_small(date(2026, 11, 9))
    assert plan == build_small(date(2026, 11, 9))
    assert (len(plan.customers), len(plan.instruments), len(plan.repairs)) == (
        50,
        100,
        150,
    )
    assert len({s.data.identification_number for s in plan.instruments}) == 100
    assert all(
        s.data.email is None or s.data.email.endswith("@example.com")
        for s in plan.customers
    )
    assert any(s.archived for s in plan.customers)
    assert any(s.data.phone is None for s in plan.customers)
    assert any(
        s.data.phone and s.data.phone.startswith("+493023125") for s in plan.customers
    )
    owners = Counter(
        s.customer_index for s in plan.instruments if s.customer_index is not None
    )
    assert len(owners) == 40 and max(owners.values()) > 1
    assert {s.data.ownership for s in plan.instruments} == {
        "customer",
        "workshop",
        "unassigned",
    }
    assert {s.history[-1][0] for s in plan.repairs} == set(RepairStatus)
    for spec in plan.repairs:
        assert spec.created_at <= spec.data.accepted_at <= spec.history[-1][1]
        assert spec.history[-1][1].date() <= plan.as_of
        if spec.data.performed_at is not None:
            assert spec.data.performed_at >= spec.data.accepted_at
        for (previous, _), (target, _) in pairwise(spec.history):
            validate_transition(previous, target)
        assert isinstance(spec.line.unit_price, Decimal)
    open_due = [
        s.data.expected_completion_date
        for s in plan.repairs
        if s.history[-1][0] not in {RepairStatus.COMPLETED, RepairStatus.CANCELLED}
    ]
    assert plan.as_of in open_due
    assert any(d < plan.as_of for d in open_due if d)
    assert any(d > plan.as_of for d in open_due if d)


def test_reference_date_keeps_manufacture_before_all_repair_history():
    plan = build_small(date(2020, 1, 1))
    for spec in plan.repairs:
        year = plan.instruments[spec.instrument_index].data.year_of_manufacture
        assert year is None or year <= spec.created_at.year
        if spec.history[-1][0] not in {RepairStatus.COMPLETED, RepairStatus.CANCELLED}:
            assert not plan.instruments[spec.instrument_index].archived
            assert not plan.customers[spec.customer_index].archived
