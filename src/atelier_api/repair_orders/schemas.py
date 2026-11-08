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
    model_validator,
)

from atelier_api.instruments.schemas import InstrumentRead

from .item_schemas import UnitPrice
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
    template_id: int | None = Field(default=None, gt=0)
    template_unit_price: UnitPrice | None = None
    work_description: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=10000),
    ] = None
    accepted_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    expected_completion_date: date | None = None
    status: RepairStatus = RepairStatus.ACCEPTED
    internal_notes: str | None = Field(default=None, max_length=10000)
    performed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def require_description_or_template(self) -> RepairOrderRegister:
        if self.template_id is None:
            if self.work_description is None:
                raise ValueError("Repair description or template is required")
            if "template_unit_price" in self.model_fields_set:
                raise ValueError("Template price requires a template")
        elif (
            "work_description" in self.model_fields_set
            and self.work_description is None
        ):
            raise ValueError("Repair description cannot be null")
        return self

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


class RepairOrderUpdate(BaseModel):
    """Preserve omitted fields; allow null only for the date and internal notes."""

    model_config = ConfigDict(extra="forbid")
    work_description: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=10000),
    ] = None
    expected_completion_date: date | None = None
    internal_notes: str | None = Field(default=None, max_length=10000)

    @field_validator("work_description")
    @classmethod
    def require_description(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Repair description cannot be null")
        return value

    @field_validator("internal_notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class RepairStatusUpdate(BaseModel):
    """Request a target state without accepting client-controlled timestamps."""

    model_config = ConfigDict(extra="forbid")
    status: RepairStatus


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
    status_updated_at: AwareDatetime | None = None
    internal_notes: str | None = None

    @field_validator("created_at", "accepted_at", "performed_at", "status_updated_at")
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
