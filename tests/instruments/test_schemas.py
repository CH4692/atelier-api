import pytest
from pydantic import ValidationError

from atelier_api.instruments.schemas import (
    InstrumentCreate,
    InstrumentRead,
    InstrumentType,
)


@pytest.mark.parametrize("instrument_type", list(InstrumentType))
def test_accepts_supported_instrument_types(instrument_type):
    instrument = InstrumentCreate(type=instrument_type)
    assert instrument.type == instrument_type
    assert instrument.customer_id is None
    assert instrument.year_of_manufacture is None


def test_accepts_complete_instrument():
    instrument = InstrumentRead(
        id=1,
        type="violin",
        maker="Example maker",
        year_of_manufacture=1920,
        identification_number="LABEL-42",
        notes="Repaired top; handwritten label.",
        customer_id=2,
    )
    assert instrument.model_dump(mode="json") == {
        "id": 1,
        "type": "violin",
        "maker": "Example maker",
        "year_of_manufacture": 1920,
        "identification_number": "LABEL-42",
        "notes": "Repaired top; handwritten label.",
        "customer_id": 2,
        "ownership": "customer",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"type": None},
        {"type": "piano"},
        {"type": ""},
        {"type": "violin", "year_of_manufacture": 0},
        {"type": "violin", "year_of_manufacture": -1},
        {"type": "violin", "year_of_manufacture": 10000},
        {"type": "violin", "year_of_manufacture": "unknown"},
        {"type": "violin", "year_of_manufacture": 1920.5},
        {"type": "violin", "customer_id": 0},
        {"type": "violin", "customer_id": -1},
        {"type": "violin", "maker": 123},
        {"type": "violin", "notes": ["invalid"]},
        {"type": "violin", "id": 123},
        {"type": "violin", "unexpected": "value"},
    ],
)
def test_rejects_invalid_instrument_data(payload):
    with pytest.raises(ValidationError):
        InstrumentCreate.model_validate(payload)


def test_read_schema_requires_identifier():
    with pytest.raises(ValidationError):
        InstrumentRead.model_validate({"type": "cello"})
