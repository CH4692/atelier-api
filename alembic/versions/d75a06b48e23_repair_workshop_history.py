"""Preserve instrument repair work and related document contents.

Revision ID: d75a06b48e23
Revises: c64f95a37d12
"""

import sqlalchemy as sa

from alembic import op

revision: str = "d75a06b48e23"
down_revision: str | None = "c64f95a37d12"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "repair_order",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Integer(),
            sa.ForeignKey("instrument.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("work_description", sa.Text(), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "length(btrim(work_description)) BETWEEN 1 AND 10000",
            name="ck_repair_order_description",
        ),
    )
    op.create_index(
        "ix_repair_order_instrument_performed_id",
        "repair_order",
        ["instrument_id", "performed_at", "id"],
    )
    op.create_table(
        "repair_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "repair_order_id",
            sa.Integer(),
            sa.ForeignKey("repair_order.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "size_bytes BETWEEN 1 AND 5242880 AND octet_length(content) = size_bytes",
            name="ck_repair_document_size",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_repair_document_digest"
        ),
    )
    op.create_index(
        "ix_repair_document_order_created_id",
        "repair_document",
        ["repair_order_id", "created_at", "id"],
    )


def downgrade() -> None:
    # Removing this feature must not silently discard stored repair documents.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM repair_order) OR EXISTS (SELECT 1 FROM repair_document) THEN RAISE EXCEPTION 'Cannot downgrade: repair history or documents exist'; END IF; END $$"
    )
    op.drop_table("repair_document")
    op.drop_table("repair_order")
