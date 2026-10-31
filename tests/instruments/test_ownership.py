"""Verify ownership categories, legacy assignment semantics and merged updates."""

import pytest
from pydantic import ValidationError

from atelier_api.instruments.models import Instrument
from atelier_api.instruments.ownership import ownership_changes
from atelier_api.instruments.schemas import (
    InstrumentCreate,
    InstrumentOwnership,
    InstrumentUpdate,
)


@pytest.mark.parametrize(
    "customer_id,expected", [(None, "unassigned"), (7, "customer")]
)
def test_legacy_creation_infers_category_for_api_and_trusted_orm(customer_id, expected):
    assert (
        InstrumentCreate(type="violin", customer_id=customer_id).ownership == expected
    )
    assert Instrument(type="violin", customer_id=customer_id).ownership == expected


@pytest.mark.parametrize("ownership", list(InstrumentOwnership))
def test_categories_can_represent_unknown_customer_owner(ownership):
    instrument = InstrumentCreate(type="violin", ownership=ownership)
    assert instrument.ownership == ownership
    assert instrument.customer_id is None


@pytest.mark.parametrize("ownership", ["workshop", "unassigned", "unknown", None])
def test_invalid_owner_category_combinations_are_rejected(ownership):
    with pytest.raises(ValidationError):
        InstrumentCreate(type="violin", customer_id=7, ownership=ownership)


@pytest.mark.parametrize("ownership", ["unknown", None])
def test_invalid_patch_categories_are_rejected(ownership):
    with pytest.raises(ValidationError):
        InstrumentUpdate(ownership=ownership)


def test_merged_patch_requires_explicit_owner_clearance(client, mock_session):
    original = Instrument(id=1, type="violin", customer_id=7)
    mock_session.get.return_value = original
    response = client.patch("/api/v1/instruments/1", json={"ownership": "workshop"})
    assert response.status_code == 422
    assert original.customer_id == 7 and original.ownership == "customer"
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize(
    "original,patch,expected",
    [
        ("customer", {"customer_id": None}, "unassigned"),
        ("workshop", {"customer_id": None}, "workshop"),
        ("unassigned", {"customer_id": 8}, "customer"),
        ("customer", {"ownership": "workshop", "customer_id": None}, "workshop"),
        ("customer", {"ownership": "customer", "customer_id": None}, "customer"),
    ],
)
def test_ownership_patch_semantics(original, patch, expected):
    instrument = Instrument(
        type="violin",
        ownership=original,
        customer_id=7 if original == "customer" else None,
    )
    changes = ownership_changes(instrument, InstrumentUpdate.model_validate(patch))
    assert changes["ownership"] == expected


def test_ownership_filter_rejects_invalid_category(client, mock_session):
    assert (
        client.get("/api/v1/instruments", params={"ownership": "bad"}).status_code
        == 422
    )
    mock_session.exec.assert_not_called()


def test_history_of_unknown_instrument_returns_404(client, mock_session):
    mock_session.get.return_value = None
    mock_session.exec.return_value.first.return_value = None
    assert client.get("/api/v1/instruments/999/ownership-history").status_code == 404
