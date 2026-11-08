"""Store independent repair estimate revisions and customer approval records.

Revision ID: b83e71f09526
Revises: a72d90e46c15
"""

import sqlalchemy as sa

from alembic import op

revision: str = "b83e71f09526"
down_revision: str | None = "a72d90e46c15"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "repair_estimate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repair_order_id", sa.Integer(), sa.ForeignKey("repair_order.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer()),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approval_method", sa.String(16)),
        sa.Column("approval_recorded_at", sa.DateTime(timezone=True)),
        sa.Column("approval_recorded_by", sa.Integer()),
        sa.Column("approval_reference", sa.String(500)),
        sa.UniqueConstraint("repair_order_id", "revision", name="uq_estimate_repair_revision"),
        sa.CheckConstraint("revision > 0", name="ck_estimate_revision"),
        sa.CheckConstraint("status IN ('draft', 'issued', 'approved', 'rejected', 'withdrawn')", name="ck_estimate_status"),
        sa.CheckConstraint("status_updated_at >= created_at", name="ck_estimate_status_time"),
        sa.CheckConstraint("status NOT IN ('issued', 'approved', 'rejected') OR issued_at IS NOT NULL", name="ck_estimate_issued"),
        sa.CheckConstraint("(status = 'approved' AND approved_at IS NOT NULL AND approval_method IS NOT NULL AND approval_recorded_at IS NOT NULL) OR (status <> 'approved' AND approved_at IS NULL AND approval_method IS NULL AND approval_recorded_at IS NULL AND approval_recorded_by IS NULL AND approval_reference IS NULL)", name="ck_estimate_approval"),
        sa.CheckConstraint("approved_at IS NULL OR (approved_at >= issued_at AND approval_recorded_at >= approved_at)", name="ck_estimate_approval_time"),
        sa.CheckConstraint("approval_method IN ('in_person', 'phone', 'email', 'written')", name="ck_estimate_approval_method"),
        sa.CheckConstraint("approval_reference IS NULL OR length(approval_reference) <= 500", name="ck_estimate_reference"),
    )
    op.create_index("ix_repair_estimate_repair_order_id", "repair_estimate", ["repair_order_id"])
    op.create_index("ix_repair_estimate_customer_id", "repair_estimate", ["customer_id"])
    op.create_table(
        "estimate_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("estimate_id", sa.Integer(), sa.ForeignKey("repair_estimate.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(9, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint("kind IN ('service', 'material')", name="ck_estimate_item_kind"),
        sa.CheckConstraint("length(btrim(description)) BETWEEN 1 AND 2000", name="ck_estimate_item_description"),
        sa.CheckConstraint("quantity > 0 AND quantity <= 999999.999", name="ck_estimate_item_quantity"),
        sa.CheckConstraint("unit_price >= 0 AND unit_price <= 9999999999.99", name="ck_estimate_item_price"),
    )
    op.create_index("ix_estimate_item_estimate_id", "estimate_item", ["estimate_id"])


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM repair_estimate) OR EXISTS (SELECT 1 FROM estimate_item) THEN
            RAISE EXCEPTION 'Repair estimates exist; review and export documents before downgrade';
        END IF;
    END $$""")
    op.drop_table("estimate_item")
    op.drop_table("repair_estimate")
