"""Validate draft positions and staff-recorded approval without client-set actors."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from atelier_api.repair_orders.item_schemas import RepairItemCreate

from .statuses import ApprovalMethod, EstimateStatus


class EstimateWrite(BaseModel):
    """Create or replace a draft's complete set of bounded estimated positions."""

    model_config = ConfigDict(extra="forbid")
    items: list[RepairItemCreate] = Field(min_length=1, max_length=200)


class EstimateTransition(BaseModel):
    """Use the dedicated approval operation for the approved state."""

    model_config = ConfigDict(extra="forbid")
    status: Literal[
        EstimateStatus.ISSUED, EstimateStatus.REJECTED, EstimateStatus.WITHDRAWN
    ]


class EstimateApproval(BaseModel):
    """Record when and how the contracting customer approved this exact document."""

    model_config = ConfigDict(extra="forbid")
    approved_at: AwareDatetime
    approval_method: ApprovalMethod
    approval_reference: str | None = Field(default=None, max_length=500)

    @field_validator("approved_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("approval_reference")
    @classmethod
    def trim_reference(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class EstimateSummary(BaseModel):
    """Expose the stored document identity, state and original approval facts."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    repair_order_id: int
    customer_id: int
    revision: int
    status: EstimateStatus
    created_at: AwareDatetime
    created_by: int | None
    status_updated_at: AwareDatetime
    issued_at: AwareDatetime | None
    approved_at: AwareDatetime | None
    approval_method: ApprovalMethod | None
    approval_recorded_at: AwareDatetime | None
    approval_recorded_by: int | None
    approval_reference: str | None

    @field_validator(
        "created_at",
        "status_updated_at",
        "issued_at",
        "approved_at",
        "approval_recorded_at",
    )
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class EstimateItemRead(RepairItemCreate):
    """Return a position with its exact rounded line amount."""

    id: int
    estimate_id: int
    line_total: Decimal


class EstimateRead(EstimateSummary):
    """Read one bounded estimate snapshot and consistently rounded totals."""

    items: list[EstimateItemRead]
    service_total: Decimal
    material_total: Decimal
    total: Decimal
