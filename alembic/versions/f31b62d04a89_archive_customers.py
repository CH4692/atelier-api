"""Add reversible archive state without changing historical associations.

Revision ID: f31b62d04a89
Revises: e15b90d6a428
"""

import sqlalchemy as sa

from alembic import op

revision: str = "f31b62d04a89"
down_revision: str | None = "e15b90d6a428"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("customer", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("customer", "is_archived", server_default=None)


def downgrade() -> None:
    op.drop_column("customer", "is_archived")
