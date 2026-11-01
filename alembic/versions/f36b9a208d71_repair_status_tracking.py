"""Add status timestamps without inventing historical change dates.

Revision ID: f36b9a208d71
Revises: 2caf51093d78
"""

import sqlalchemy as sa

from alembic import op

revision: str = "f36b9a208d71"
down_revision: str | None = "2caf51093d78"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Existing status-change times are unknown, even when intake dates are known.
    op.add_column("repair_order", sa.Column("status_updated_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_repair_order_status_time", "repair_order",
        "status_updated_at IS NULL OR accepted_at IS NULL OR status_updated_at >= accepted_at",
    )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM repair_order WHERE status_updated_at IS NOT NULL) THEN
            RAISE EXCEPTION 'Repair status timestamps exist; review and export records before downgrade';
        END IF;
    END $$""")
    op.drop_constraint("ck_repair_order_status_time", "repair_order", type_="check")
    op.drop_column("repair_order", "status_updated_at")
