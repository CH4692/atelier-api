"""Add customer-linked repair intake while preserving unattributed work history.

Revision ID: 2caf51093d78
Revises: 1b9e40f82c67
"""

import sqlalchemy as sa

from alembic import op

revision: str = "2caf51093d78"
down_revision: str | None = "1b9e40f82c67"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Historical work has neither a verified accepting customer nor intake date.
    # Never infer these facts from today's owner or rewrite performed_at.
    op.add_column("repair_order", sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customer.id", name="fk_repair_order_customer", ondelete="RESTRICT")))
    op.add_column("repair_order", sa.Column("accepted_at", sa.DateTime(timezone=True)))
    op.add_column("repair_order", sa.Column("expected_completion_date", sa.Date()))
    op.add_column("repair_order", sa.Column("status", sa.String(32), nullable=False, server_default="completed"))
    op.add_column("repair_order", sa.Column("internal_notes", sa.Text()))
    op.alter_column("repair_order", "performed_at", existing_type=sa.DateTime(timezone=True), nullable=True)
    op.create_index("ix_repair_order_customer_id", "repair_order", ["customer_id"])
    op.create_check_constraint("ck_repair_order_status", "repair_order", "status IN ('accepted', 'awaiting_approval', 'in_progress', 'awaiting_materials', 'ready_for_pickup', 'completed', 'cancelled')")
    op.create_check_constraint("ck_repair_order_notes", "repair_order", "internal_notes IS NULL OR length(internal_notes) <= 10000")
    op.create_check_constraint("ck_repair_order_accepted_customer", "repair_order", "accepted_at IS NULL OR customer_id IS NOT NULL")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM repair_order WHERE performed_at IS NULL
            OR customer_id IS NOT NULL OR accepted_at IS NOT NULL
            OR expected_completion_date IS NOT NULL OR internal_notes IS NOT NULL
            OR status <> 'completed') THEN
            RAISE EXCEPTION 'Review managed repair orders before downgrade; intake data would be lost';
        END IF;
    END $$""")
    for name in ("ck_repair_order_accepted_customer", "ck_repair_order_notes", "ck_repair_order_status"):
        op.drop_constraint(name, "repair_order", type_="check")
    op.drop_index("ix_repair_order_customer_id", table_name="repair_order")
    op.drop_constraint("fk_repair_order_customer", "repair_order", type_="foreignkey")
    for name in ("internal_notes", "status", "expected_completion_date", "accepted_at", "customer_id"):
        op.drop_column("repair_order", name)
    op.alter_column("repair_order", "performed_at", existing_type=sa.DateTime(timezone=True), nullable=False)
