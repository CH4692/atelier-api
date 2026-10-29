"""Add privacy-minimized application audit events.

Revision ID: e15b90d6a428
Revises: d03a8f762c11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e15b90d6a428"
down_revision: str | Sequence[str] | None = "d03a8f762c11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create independent historical identifiers without cascading foreign keys."""
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    for name in ("action", "resource_type", "resource_id", "actor_id", "occurred_at"):
        op.create_index(f"ix_audit_event_{name}", "audit_event", [name])


def downgrade() -> None:
    """Remove audit history when explicitly rolling back this feature."""
    op.drop_table("audit_event")
