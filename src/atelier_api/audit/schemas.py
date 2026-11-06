"""Expose only audit facts and explicitly allowed administrative change details."""

from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from atelier_api.estimates.statuses import EstimateStatus
from atelier_api.repair_orders.statuses import RepairStatus
from atelier_api.users.roles import UserRole


class AuditDetails(BaseModel):
    """Allow only non-secret identifiers, roles and repair states in event details."""

    model_config = ConfigDict(extra="forbid")
    estimate_status: EstimateStatus | None = None
    previous_estimate_status: EstimateStatus | None = None
    repair_order_id: int | None = Field(default=None, gt=0)
    previous_status: RepairStatus | None = None
    new_status: RepairStatus | None = None
    previous_role: UserRole | None = None
    new_role: UserRole | None = None
    previous_customer_id: int | None = Field(default=None, gt=0)
    new_customer_id: int | None = Field(default=None, gt=0)
    execution_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    instrument_id: int | None = Field(default=None, gt=0)
    removed_count: int | None = Field(default=None, ge=0)


class AuditEventRead(BaseModel):
    """Return minimal historical facts without joining account or customer data."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    resource_type: str
    resource_id: int | None
    actor_id: int | None
    occurred_at: AwareDatetime
    succeeded: bool
    details: AuditDetails

    @field_validator("occurred_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Return UTC even when the database session uses another timezone."""
        return value.astimezone(UTC)
