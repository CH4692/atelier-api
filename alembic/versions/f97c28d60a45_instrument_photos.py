"""Persist instrument photo metadata and recoverable upload intents.

Revision ID: f97c28d60a45
Revises: e86b17c59f34
"""

import sqlalchemy as sa

from alembic import op

revision: str = "f97c28d60a45"
down_revision: str | None = "e86b17c59f34"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "instrument_photo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), sa.ForeignKey("instrument.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("storage_namespace", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(200), unique=True, nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True)),
        sa.Column("deletion_requested_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.CheckConstraint("file_size_bytes BETWEEN 1 AND 10000000", name="ck_photo_size"),
        sa.CheckConstraint("content_type IN ('image/jpeg', 'image/png', 'image/webp')", name="ck_photo_content_type"),
        sa.CheckConstraint("status IN ('pending', 'ready', 'deleted')", name="ck_photo_status"),
        sa.CheckConstraint("length(btrim(original_filename)) BETWEEN 1 AND 255", name="ck_photo_filename"),
        sa.CheckConstraint("(status = 'deleted' AND deletion_requested_at IS NOT NULL) OR (status <> 'deleted' AND deletion_requested_at IS NULL)", name="ck_photo_deletion"),
    )
    op.create_index("ix_instrument_photo_instrument_status_id", "instrument_photo", ["instrument_id", "status", "id"])
    op.create_index("ix_instrument_photo_status_uploaded_at", "instrument_photo", ["status", "uploaded_at"])


def downgrade() -> None:
    op.drop_table("instrument_photo")
