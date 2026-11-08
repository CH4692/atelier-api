"""Store reusable repair templates independently of historical repair values.

Revision ID: c94e82a10637
Revises: b83e71f09526
"""

import sqlalchemy as sa

from alembic import op

revision: str = "c94e82a10637"
down_revision: str | None = "b83e71f09526"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "repair_template",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("default_unit_price", sa.Numeric(12, 2)),
        sa.CheckConstraint("length(btrim(name)) BETWEEN 1 AND 100", name="ck_repair_template_name"),
        sa.CheckConstraint("length(btrim(description)) BETWEEN 1 AND 2000", name="ck_repair_template_description"),
        sa.CheckConstraint("default_unit_price >= 0 AND default_unit_price <= 9999999999.99", name="ck_repair_template_price"),
    )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM repair_template) THEN
            RAISE EXCEPTION 'Refusing to delete repair templates';
        END IF;
    END $$""")
    op.drop_table("repair_template")
