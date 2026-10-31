"""Expose only audit facts and explicitly allowed administrative change details."""

from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from atelier_api.users.roles import UserRole


class AuditDetails(BaseModel):
    """Allow only non-secret identifiers and role transitions in event details."""

    model_config = ConfigDict(extra="forbid")
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
