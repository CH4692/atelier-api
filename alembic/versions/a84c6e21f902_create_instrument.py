"""Create instruments with an optional customer association.

Revision ID: a84c6e21f902
Revises: 66cdf18dbf11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlmodel.sql.sqltypes import AutoString

from alembic import op

revision: str = "a84c6e21f902"
down_revision: str | Sequence[str] | None = "66cdf18dbf11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the instrument table and its customer lookup index."""
    op.create_table(
        "instrument",
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("maker", AutoString(), nullable=True),
        sa.Column("year_of_manufacture", sa.Integer(), nullable=True),
        sa.Column("identification_number", AutoString(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "type IN ('violin', 'viola', 'cello', 'double_bass')",
            name="ck_instrument_type",
        ),
        sa.CheckConstraint(
            "year_of_manufacture BETWEEN 1 AND 9999",
            name="ck_instrument_year_of_manufacture",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_instrument_customer_id", "instrument", ["customer_id"])


def downgrade() -> None:
    """Remove instruments while keeping customer records intact."""
    op.drop_index("ix_instrument_customer_id", table_name="instrument")
    op.drop_table("instrument")
