"""Support bows and optional category-specific instrument measurements.

Revision ID: c64f95a37d12
Revises: b53e84f26c01
"""

import sqlalchemy as sa

from alembic import op

revision: str = "c64f95a37d12"
down_revision: str | None = "b53e84f26c01"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_instrument_type", "instrument", type_="check")
    op.create_check_constraint(
        "ck_instrument_type",
        "instrument",
        "type IN ('violin', 'viola', 'cello', 'double_bass', 'bow')",
    )
    op.add_column("instrument", sa.Column("body_length_mm", sa.Float(), nullable=True))
    op.add_column("instrument", sa.Column("bow_weight_g", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_instrument_body_length",
        "instrument",
        "body_length_mm > 0 AND body_length_mm < 'Infinity'::double precision",
    )
    op.create_check_constraint(
        "ck_instrument_bow_weight",
        "instrument",
        "bow_weight_g > 0 AND bow_weight_g < 'Infinity'::double precision",
    )
    op.create_check_constraint(
        "ck_instrument_category_attributes",
        "instrument",
        "(type = 'bow' AND body_length_mm IS NULL) OR (type <> 'bow' AND bow_weight_g IS NULL)",
    )
    op.create_index("ix_instrument_type", "instrument", ["type"])


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM instrument WHERE type = 'bow' OR body_length_mm IS NOT NULL OR bow_weight_g IS NOT NULL) THEN RAISE EXCEPTION 'Cannot downgrade: bows or category-specific measurements exist'; END IF; END $$"
    )
    op.drop_index("ix_instrument_type", table_name="instrument")
    for name in (
        "ck_instrument_category_attributes",
        "ck_instrument_bow_weight",
        "ck_instrument_body_length",
    ):
        op.drop_constraint(name, "instrument", type_="check")
    op.drop_column("instrument", "bow_weight_g")
    op.drop_column("instrument", "body_length_mm")
    op.drop_constraint("ck_instrument_type", "instrument", type_="check")
    op.create_check_constraint(
        "ck_instrument_type",
        "instrument",
        "type IN ('violin', 'viola', 'cello', 'double_bass')",
    )
