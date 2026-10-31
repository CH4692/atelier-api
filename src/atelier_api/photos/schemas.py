"""Expose photo metadata without bucket names, object keys or credentials."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class PhotoRead(BaseModel):
    """Represent a successfully stored photograph, including deletion requests."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    instrument_id: int
    original_filename: str
    content_type: str
    file_size_bytes: int
    uploaded_at: AwareDatetime
    uploaded_by_user_id: int | None
    status: Literal["ready", "deleted"]
    deletion_requested_at: AwareDatetime | None
    deletion_requested_by_user_id: int | None

    @field_validator("uploaded_at", "deletion_requested_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value else None


class RetentionHoldCreate(BaseModel):
    """Accept a minimal retention justification without logging its contents."""

    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("A retention hold needs a valid reason")
        return value


class PurgeApproval(BaseModel):
    """Require explicit review of other documentation/contract retention needs."""

    model_config = ConfigDict(extra="forbid")
    confirm_no_retention_requirements: Literal[True]

    @field_validator("confirm_no_retention_requirements", mode="before")
    @classmethod
    def require_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit boolean confirmation is required")
        return value


class PhotoRetentionRead(BaseModel):
    """Expose lifecycle safeguards only through administrator operations."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    instrument_id: int
    status: Literal["ready", "deleted", "purging"]
    retention_hold_reason: str | None
    retention_hold_at: AwareDatetime | None
    retention_hold_by_user_id: int | None
    purge_approved_at: AwareDatetime | None
    purge_approved_by_user_id: int | None

    @field_validator("retention_hold_at", "purge_approved_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value else None
