"""Persist issued estimate snapshots and recorded customer approval facts."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import CheckConstraint, DateTime, Enum, Numeric, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from atelier_api.repair_orders.item_models import RepairItemKind

from .statuses import ApprovalMethod, EstimateStatus


class RepairEstimate(SQLModel, table=True):
    """Retain each document revision and its original contracting customer."""

    __tablename__: ClassVar[str] = "repair_estimate"
    __table_args__ = (
        UniqueConstraint(
            "repair_order_id", "revision", name="uq_estimate_repair_revision"
        ),
        CheckConstraint("revision > 0", name="ck_estimate_revision"),
        CheckConstraint(
            "status_updated_at >= created_at", name="ck_estimate_status_time"
        ),
        CheckConstraint(
            "status NOT IN ('issued', 'approved', 'rejected') OR issued_at IS NOT NULL",
            name="ck_estimate_issued",
        ),
        CheckConstraint(
            "(status = 'approved' AND approved_at IS NOT NULL AND approval_method IS NOT NULL AND approval_recorded_at IS NOT NULL) OR (status <> 'approved' AND approved_at IS NULL AND approval_method IS NULL AND approval_recorded_at IS NULL AND approval_recorded_by IS NULL AND approval_reference IS NULL)",
            name="ck_estimate_approval",
        ),
        CheckConstraint(
            "approved_at IS NULL OR (approved_at >= issued_at AND approval_recorded_at >= approved_at)",
            name="ck_estimate_approval_time",
        ),
        CheckConstraint(
            "approval_reference IS NULL OR length(approval_reference) <= 500",
            name="ck_estimate_reference",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    repair_order_id: int = Field(
        foreign_key="repair_order.id", ondelete="RESTRICT", index=True
    )
    customer_id: int = Field(foreign_key="customer.id", ondelete="RESTRICT", index=True)
    revision: int
    status: EstimateStatus = Field(
        default=EstimateStatus.DRAFT,
        sa_type=Enum(
            EstimateStatus,
            values_callable=lambda entries: [entry.value for entry in entries],
            native_enum=False,
            create_constraint=True,
            name="ck_estimate_status",
            length=16,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), sa_type=DateTime(timezone=True)
    )
    created_by: int | None = None
    status_updated_at: datetime = Field(sa_type=DateTime(timezone=True))
    issued_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    approved_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    approval_method: ApprovalMethod | None = Field(
        default=None,
        sa_type=Enum(
            ApprovalMethod,
            values_callable=lambda entries: [entry.value for entry in entries],
            native_enum=False,
            create_constraint=True,
            name="ck_estimate_approval_method",
            length=16,
        ),
    )
    approval_recorded_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    approval_recorded_by: int | None = None
    approval_reference: str | None = Field(default=None, max_length=500)


class EstimateItem(SQLModel, table=True):
    """Store estimated lines independently of the actual repair_item table."""

    __tablename__: ClassVar[str] = "estimate_item"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(description)) BETWEEN 1 AND 2000",
            name="ck_estimate_item_description",
        ),
        CheckConstraint(
            "quantity > 0 AND quantity <= 999999.999", name="ck_estimate_item_quantity"
        ),
        CheckConstraint(
            "unit_price >= 0 AND unit_price <= 9999999999.99",
            name="ck_estimate_item_price",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    estimate_id: int = Field(
        foreign_key="repair_estimate.id", ondelete="RESTRICT", index=True
    )
    kind: RepairItemKind = Field(
        sa_type=Enum(
            RepairItemKind,
            values_callable=lambda entries: [entry.value for entry in entries],
            native_enum=False,
            create_constraint=True,
            name="ck_estimate_item_kind",
            length=16,
        )
    )
    description: str = Field(sa_type=Text)
    quantity: Decimal = Field(sa_type=Numeric(9, 3))
    unit_price: Decimal = Field(sa_type=Numeric(12, 2))
