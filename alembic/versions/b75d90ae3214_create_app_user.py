"""Create application users with unique emails and hashed passwords.

Revision ID: b75d90ae3214
Revises: a84c6e21f902
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b75d90ae3214"
down_revision: str | Sequence[str] | None = "a84c6e21f902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create accounts with database-enforced uniqueness and hash storage."""
    op.create_table(
        "app_user",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "email = lower(email) AND email = btrim(email) AND length(email) > 0",
            name="ck_app_user_normalized_email",
        ),
        sa.CheckConstraint(
            "hashed_password LIKE '$argon2id$%'",
            name="ck_app_user_password_hash",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
    )


def downgrade() -> None:
    """Remove accounts while preserving customers and instruments."""
    op.drop_table("app_user")
