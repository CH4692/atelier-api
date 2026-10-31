"""Validate categories and optional measurements without silently dropping data."""

import pytest
from pydantic import ValidationError

from atelier_api.instruments.models import Instrument
from atelier_api.instruments.schemas import (
    InstrumentCreate,
    InstrumentType,
    InstrumentUpdate,
)


@pytest.mark.parametrize("category", list(InstrumentType))
def test_every_category_can_be_registered_without_measurements(category):
    instrument = InstrumentCreate(type=category)
    assert instrument.body_length_mm is None and instrument.bow_weight_g is None


@pytest.mark.parametrize(
    "category,values",
    [
        ("bow", {"bow_weight_g": 60.5}),
        ("violin", {"body_length_mm": 355}),
        ("viola", {"body_length_mm": 410}),
        ("cello", {"body_length_mm": 755}),
        ("double_bass", {"body_length_mm": 1100}),
    ],
)
def test_optional_measurements_for_matching_category(category, values):
    instrument = InstrumentCreate(type=category, **values)
    for name, value in values.items():
        assert getattr(instrument, name) == value


@pytest.mark.parametrize(
    "category,values",
    [
        ("bow", {"body_length_mm": 355}),
        ("violin", {"bow_weight_g": 60}),
        ("viola", {"bow_weight_g": 60}),
        ("cello", {"bow_weight_g": 60}),
        ("double_bass", {"bow_weight_g": 60}),
    ],
)
def test_irrelevant_measurements_are_rejected(category, values):
    with pytest.raises(ValidationError):
        InstrumentCreate(type=category, **values)


@pytest.mark.parametrize("schema", [InstrumentCreate, InstrumentUpdate])
@pytest.mark.parametrize("name", ["body_length_mm", "bow_weight_g"])
@pytest.mark.parametrize(
    "value", [0, -1, float("nan"), float("inf"), "invalid", True, "60"]
)
def test_invalid_measurements_are_rejected(schema, name, value):
    with pytest.raises(ValidationError):
        schema.model_validate(
            {"type": "bow" if name == "bow_weight_g" else "violin", name: value}
        )


def test_patch_validates_category_against_existing_measurements(client, mock_session):
    instrument = Instrument(id=1, type="violin", body_length_mm=355)
    mock_session.get.return_value = instrument
    response = client.patch("/api/v1/instruments/1", json={"type": "bow"})
    assert response.status_code == 422
    assert instrument.type == "violin" and instrument.body_length_mm == 355
    mock_session.commit.assert_not_called()
    response = client.patch(
        "/api/v1/instruments/1",
        json={"type": "bow", "body_length_mm": None, "bow_weight_g": 60},
    )
    assert response.status_code == 200
    assert response.json()["bow_weight_g"] == 60
    assert response.json()["body_length_mm"] is None


def test_patch_rejects_wrong_measurement_without_type_change(client, mock_session):
    mock_session.get.return_value = Instrument(id=1, type="bow")
    assert (
        client.patch("/api/v1/instruments/1", json={"body_length_mm": 355}).status_code
        == 422
    )
    mock_session.commit.assert_not_called()


def test_filter_categories_and_ownership_together(client, mock_session):
    mock_session.exec.return_value.all.return_value = []
    response = client.get(
        "/api/v1/instruments", params={"type": "bow", "ownership": "workshop"}
    )
    assert response.status_code == 200 and response.json() == []
    statement = mock_session.exec.call_args.args[0]
    assert {"bow", "workshop"} <= set(statement.compile().params.values())


@pytest.mark.parametrize("category", ["piano", "BOW", ""])
def test_invalid_category_filter_returns_422(client, mock_session, category):
    assert (
        client.get("/api/v1/instruments", params={"type": category}).status_code == 422
    )
    mock_session.exec.assert_not_called()
