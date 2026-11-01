"""Describe repair work and document metadata without serializing binary contents."""

from datetime import UTC, date, datetime
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
)

from atelier_api.instruments.schemas import InstrumentRead

from .statuses import RepairStatus


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


class RepairOrderRegister(BaseModel):
    """Accept a customer-linked order without inventing a completed-work date."""

    model_config = ConfigDict(extra="forbid")
    customer_id: int = Field(gt=0)
    instrument_id: int = Field(gt=0)
    work_description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)
    ]
    accepted_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    expected_completion_date: date | None = None
    status: RepairStatus = RepairStatus.ACCEPTED
    internal_notes: str | None = Field(default=None, max_length=10000)
    performed_at: AwareDatetime | None = None

    @field_validator("accepted_at", "performed_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @field_validator("internal_notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is not None:
            return value.strip() or None
        return None


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


class RepairOrderRead(BaseModel):
    """Return current orders and preserved historical work with explicit unknowns."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    instrument_id: int
    work_description: str
    performed_at: AwareDatetime | None
    created_at: AwareDatetime
    is_archived: bool
    customer_id: int | None = None
    accepted_at: AwareDatetime | None = None
    expected_completion_date: date | None = None
    status: RepairStatus = RepairStatus.COMPLETED
    internal_notes: str | None = None

    @field_validator("created_at", "accepted_at", "performed_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class RepairOrderDetail(RepairOrderRead):
    """Include documents belonging to this repair order only."""

    documents: list[RepairDocumentRead]


class InstrumentHistoryRead(BaseModel):
    """Compose instrument details and chronologically ordered repair history."""

    instrument: InstrumentRead
    repair_orders: list[RepairOrderDetail]
