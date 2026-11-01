"""Store exact service and material positions for repair orders.

Revision ID: a72d90e46c15
Revises: f36b9a208d71
"""

import sqlalchemy as sa

from alembic import op

revision: str = "a72d90e46c15"
down_revision: str | None = "f36b9a208d71"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "repair_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repair_order_id", sa.Integer(), sa.ForeignKey("repair_order.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(9, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint("kind IN ('service', 'material')", name="ck_repair_item_kind"),
        sa.CheckConstraint("length(btrim(description)) BETWEEN 1 AND 2000", name="ck_repair_item_description"),
        sa.CheckConstraint("quantity > 0 AND quantity <= 999999.999", name="ck_repair_item_quantity"),
        sa.CheckConstraint("unit_price >= 0 AND unit_price <= 9999999999.99", name="ck_repair_item_unit_price"),
    )
    op.create_index("ix_repair_item_repair_order_id", "repair_item", ["repair_order_id"])


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM repair_item) THEN
            RAISE EXCEPTION 'Repair items exist; review and export costs before downgrade';
        END IF;
    END $$""")
    op.drop_table("repair_item")
