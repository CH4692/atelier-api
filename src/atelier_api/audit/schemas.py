"""Expose only audit facts and explicitly allowed administrative change details."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from atelier_api.users.roles import UserRole


class AuditDetails(BaseModel):
    """Allow only non-secret identifiers and role transitions in event details."""

    model_config = ConfigDict(extra="forbid")
    previous_role: UserRole | None = None
    new_role: UserRole | None = None
    previous_customer_id: int | None = Field(default=None, gt=0)
    new_customer_id: int | None = Field(default=None, gt=0)
    removed_count: int | None = Field(default=None, ge=0)


class AuditEventRead(BaseModel):
    """Return minimal historical facts without joining account or customer data."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    resource_type: str
    resource_id: int | None
    actor_id: int | None
    occurred_at: datetime
    succeeded: bool
    details: AuditDetails
