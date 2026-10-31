"""Add recoverable retention holds, approval and durable purge state.

Revision ID: 0a8d39e71b56
Revises: f97c28d60a45
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0a8d39e71b56"
down_revision: str | None = "f97c28d60a45"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("instrument_photo", sa.Column("retention_hold_reason", sa.String(500)))
    op.add_column("instrument_photo", sa.Column("retention_hold_at", sa.DateTime(timezone=True)))
    op.add_column("instrument_photo", sa.Column("retention_hold_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id", name="fk_photo_hold_user", ondelete="SET NULL")))
    op.add_column("instrument_photo", sa.Column("purge_approved_at", sa.DateTime(timezone=True)))
    op.add_column("instrument_photo", sa.Column("purge_approved_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id", name="fk_photo_approval_user", ondelete="SET NULL")))
    op.drop_constraint("ck_photo_status", "instrument_photo", type_="check")
    op.drop_constraint("ck_photo_deletion", "instrument_photo", type_="check")
    op.create_check_constraint("ck_photo_status", "instrument_photo", "status IN ('pending', 'ready', 'deleted', 'purging')")
    op.create_check_constraint("ck_photo_deletion", "instrument_photo", "(status IN ('deleted', 'purging') AND deletion_requested_at IS NOT NULL) OR (status IN ('pending', 'ready') AND deletion_requested_at IS NULL)")
    op.create_check_constraint("ck_photo_hold", "instrument_photo", "(retention_hold_reason IS NULL AND retention_hold_at IS NULL) OR (retention_hold_reason IS NOT NULL AND length(btrim(retention_hold_reason)) BETWEEN 1 AND 500 AND retention_hold_at IS NOT NULL)")
    op.create_check_constraint("ck_photo_purging", "instrument_photo", "status <> 'purging' OR (retention_hold_reason IS NULL AND purge_approved_at IS NOT NULL)")
    op.create_index("ix_instrument_photo_status_deletion_requested_at", "instrument_photo", ["status", "deletion_requested_at", "id"])


def downgrade() -> None:
    # Never silently turn uncertain irreversible deletions into recoverable photos.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM instrument_photo WHERE status = 'purging' OR retention_hold_reason IS NOT NULL) THEN
            RAISE EXCEPTION 'Reconcile purging photographs and retention holds before downgrade';
        END IF;
    END $$""")
    op.drop_index("ix_instrument_photo_status_deletion_requested_at", table_name="instrument_photo")
    for name in ("ck_photo_hold", "ck_photo_purging", "ck_photo_status", "ck_photo_deletion"):
        op.drop_constraint(name, "instrument_photo", type_="check")
    op.create_check_constraint("ck_photo_status", "instrument_photo", "status IN ('pending', 'ready', 'deleted')")
    op.create_check_constraint("ck_photo_deletion", "instrument_photo", "(status = 'deleted' AND deletion_requested_at IS NOT NULL) OR (status <> 'deleted' AND deletion_requested_at IS NULL)")
    op.drop_constraint("fk_photo_hold_user", "instrument_photo", type_="foreignkey")
    op.drop_constraint("fk_photo_approval_user", "instrument_photo", type_="foreignkey")
    for name in ("retention_hold_reason", "retention_hold_at", "retention_hold_by_user_id", "purge_approved_at", "purge_approved_by_user_id"):
        op.drop_column("instrument_photo", name)
