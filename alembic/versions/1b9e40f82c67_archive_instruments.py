"""Add reversible instrument archival without altering historical references.

Revision ID: 1b9e40f82c67
Revises: 0a8d39e71b56
"""

import sqlalchemy as sa

from alembic import op

revision: str = "1b9e40f82c67"
down_revision: str | None = "0a8d39e71b56"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("instrument", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_instrument_is_archived_id", "instrument", ["is_archived", "id"])


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM instrument WHERE is_archived) THEN
            RAISE EXCEPTION 'Restore archived instruments before downgrade';
        END IF;
    END $$""")
    op.drop_index("ix_instrument_is_archived_id", table_name="instrument")
    op.drop_column("instrument", "is_archived")
