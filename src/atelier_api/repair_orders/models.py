"""Store repair history and bounded document contents without cascading deletion."""

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import CheckConstraint, DateTime, Index, LargeBinary, Text
from sqlmodel import Field, SQLModel

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


class RepairOrder(SQLModel, table=True):
    """Retain dated work descriptions when an order or its customer is archived."""

    __tablename__: ClassVar[str] = "repair_order"
    __table_args__ = (
        Index(
            "ix_repair_order_instrument_performed_id",
            "instrument_id",
            "performed_at",
            "id",
        ),
        CheckConstraint(
            "length(btrim(work_description)) BETWEEN 1 AND 10000",
            name="ck_repair_order_description",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    instrument_id: int = Field(foreign_key="instrument.id", ondelete="RESTRICT")
    work_description: str = Field(sa_type=Text)
    performed_at: datetime = Field(sa_type=DateTime(timezone=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), sa_type=DateTime(timezone=True)
    )
    is_archived: bool = False


class RepairDocument(SQLModel, table=True):
    """Keep document bytes in PostgreSQL; expose metadata separately from content."""

    __tablename__: ClassVar[str] = "repair_document"
    __table_args__ = (
        Index(
            "ix_repair_document_order_created_id", "repair_order_id", "created_at", "id"
        ),
        CheckConstraint(
            f"size_bytes BETWEEN 1 AND {MAX_DOCUMENT_BYTES} AND octet_length(content) = size_bytes",
            name="ck_repair_document_size",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_repair_document_digest"),
    )
    id: int | None = Field(default=None, primary_key=True)
    repair_order_id: int = Field(foreign_key="repair_order.id", ondelete="RESTRICT")
    filename: str = Field(max_length=255)
    size_bytes: int
    sha256: str = Field(max_length=64)
    content: bytes = Field(sa_type=LargeBinary)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), sa_type=DateTime(timezone=True)
    )
