"""Describe repair work and document metadata without serializing binary contents."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StrictBool,
    StringConstraints,
    field_validator,
)

from atelier_api.instruments.schemas import InstrumentRead


class RepairOrderCreate(BaseModel):
    """Require an explicit work timestamp rather than inventing historical dates."""

    model_config = ConfigDict(extra="forbid")
    work_description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)
    ]
    performed_at: AwareDatetime

    @field_validator("performed_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class ArchiveUpdate(BaseModel):
    """Change visibility state without deleting work or documents."""

    model_config = ConfigDict(extra="forbid")
    is_archived: StrictBool


class RepairDocumentRead(BaseModel):
    """Return metadata only; content requires the separate authenticated download."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    repair_order_id: int
    filename: str
    size_bytes: int
    sha256: str
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class RepairOrderRead(RepairOrderCreate):
    """Return a preserved work entry and its archive state."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    instrument_id: int
    created_at: AwareDatetime
    is_archived: bool

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class RepairOrderDetail(RepairOrderRead):
    """Include documents belonging to this repair order only."""

    documents: list[RepairDocumentRead]


class InstrumentHistoryRead(BaseModel):
    """Compose instrument details and chronologically ordered repair history."""

    instrument: InstrumentRead
    repair_orders: list[RepairOrderDetail]
