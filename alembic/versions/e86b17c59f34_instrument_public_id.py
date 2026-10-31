"""Assign permanent random public instrument identifiers.

Revision ID: e86b17c59f34
Revises: d75a06b48e23
"""

import sqlalchemy as sa

from alembic import op

revision: str = "e86b17c59f34"
down_revision: str | None = "d75a06b48e23"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("instrument", sa.Column(
        "public_id", sa.Uuid(), nullable=False,
        server_default=sa.text("gen_random_uuid()"),
    ))
    op.create_unique_constraint("uq_instrument_public_id", "instrument", ["public_id"])
    op.execute("""
        CREATE FUNCTION prevent_instrument_public_id_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.public_id IS DISTINCT FROM OLD.public_id THEN
                RAISE EXCEPTION 'Instrument public_id is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER instrument_public_id_immutable
        BEFORE UPDATE OF public_id ON instrument
        FOR EACH ROW EXECUTE FUNCTION prevent_instrument_public_id_change();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER instrument_public_id_immutable ON instrument")
    op.execute("DROP FUNCTION prevent_instrument_public_id_change()")
    op.drop_constraint("uq_instrument_public_id", "instrument", type_="unique")
    op.drop_column("instrument", "public_id")
