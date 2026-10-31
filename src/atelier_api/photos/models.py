"""Persist photo metadata and upload intents without storing image binaries."""

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import CheckConstraint, DateTime, Index
from sqlmodel import Field, SQLModel

MAX_PHOTO_BYTES = 10_000_000
MAX_PHOTOS = 10
MAX_PIXELS = 20_000_000
MAX_REQUEST_BYTES = MAX_PHOTOS * MAX_PHOTO_BYTES + 1_000_000


class InstrumentPhoto(SQLModel, table=True):
    """Reserve keys before external writes so failed uploads remain recoverable.

    Pending rows are never exposed through ordinary APIs. Deletion requests hide
    ready photos without removing their evidence or relationships.
    """

    __tablename__: ClassVar[str] = "instrument_photo"
    __table_args__ = (
        CheckConstraint("file_size_bytes BETWEEN 1 AND 10000000", name="ck_photo_size"),
        CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_photo_content_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'deleted', 'purging')",
            name="ck_photo_status",
        ),
        CheckConstraint(
            "length(btrim(original_filename)) BETWEEN 1 AND 255",
            name="ck_photo_filename",
        ),
        CheckConstraint(
            "(status IN ('deleted', 'purging') AND deletion_requested_at IS NOT NULL) OR (status IN ('pending', 'ready') AND deletion_requested_at IS NULL)",
            name="ck_photo_deletion",
        ),
        CheckConstraint(
            "(retention_hold_reason IS NULL AND retention_hold_at IS NULL) OR (retention_hold_reason IS NOT NULL AND length(btrim(retention_hold_reason)) BETWEEN 1 AND 500 AND retention_hold_at IS NOT NULL)",
            name="ck_photo_hold",
        ),
        CheckConstraint(
            "status <> 'purging' OR (retention_hold_reason IS NULL AND purge_approved_at IS NOT NULL)",
            name="ck_photo_purging",
        ),
        Index(
            "ix_instrument_photo_status_deletion_requested_at",
            "status",
            "deletion_requested_at",
            "id",
        ),
        Index(
            "ix_instrument_photo_instrument_status_id", "instrument_id", "status", "id"
        ),
        Index("ix_instrument_photo_status_uploaded_at", "status", "uploaded_at"),
    )
    id: int | None = Field(default=None, primary_key=True)
    instrument_id: int = Field(foreign_key="instrument.id", ondelete="RESTRICT")
    storage_namespace: str = Field(max_length=64, repr=False)
    storage_key: str = Field(max_length=200, unique=True, repr=False)
    original_filename: str = Field(max_length=255)
    content_type: str = Field(max_length=32)
    file_size_bytes: int
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), sa_type=DateTime(timezone=True)
    )
    uploaded_by_user_id: int | None = Field(
        default=None, foreign_key="app_user.id", ondelete="SET NULL"
    )
    status: str = Field(default="pending", max_length=16)
    deletion_requested_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    deletion_requested_by_user_id: int | None = Field(
        default=None, foreign_key="app_user.id", ondelete="SET NULL"
    )
    retention_hold_reason: str | None = Field(default=None, max_length=500)
    retention_hold_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    retention_hold_by_user_id: int | None = Field(
        default=None, foreign_key="app_user.id", ondelete="SET NULL"
    )
    purge_approved_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    purge_approved_by_user_id: int | None = Field(
        default=None, foreign_key="app_user.id", ondelete="SET NULL"
    )
