"""Add explicit ownership and transactionally retained ownership history.

Revision ID: b53e84f26c01
Revises: a42d73e15b90
"""

import sqlalchemy as sa

from alembic import op

revision: str = "b53e84f26c01"
down_revision: str | None = "a42d73e15b90"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "instrument",
        sa.Column(
            "ownership", sa.String(16), nullable=False, server_default="unassigned"
        ),
    )
    op.execute(
        "UPDATE instrument SET ownership = 'customer' WHERE customer_id IS NOT NULL"
    )
    op.alter_column("instrument", "ownership", server_default=None)
    op.create_check_constraint(
        "ck_instrument_ownership",
        "instrument",
        "ownership IN ('customer', 'workshop', 'unassigned')",
    )
    op.create_check_constraint(
        "ck_instrument_owner_category",
        "instrument",
        "customer_id IS NULL OR ownership = 'customer'",
    )
    op.create_index("ix_instrument_ownership", "instrument", ["ownership"])
    op.create_table(
        "instrument_ownership_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("previous_ownership", sa.String(16), nullable=True),
        sa.Column("previous_customer_id", sa.Integer(), nullable=True),
        sa.Column("ownership", sa.String(16), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_instrument_ownership_event_instrument_id_id",
        "instrument_ownership_event",
        ["instrument_id", "id"],
    )
    op.execute(
        "INSERT INTO instrument_ownership_event (instrument_id, ownership, customer_id, source) SELECT id, ownership, customer_id, 'migration' FROM instrument"
    )
    op.execute("""
        CREATE FUNCTION record_instrument_ownership() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE old_category varchar(16); old_customer integer;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF OLD.ownership IS NOT DISTINCT FROM NEW.ownership
                    AND OLD.customer_id IS NOT DISTINCT FROM NEW.customer_id THEN
                    RETURN NEW;
                END IF;
                old_category := OLD.ownership;
                old_customer := OLD.customer_id;
            END IF;
            INSERT INTO instrument_ownership_event
                (instrument_id, previous_ownership, previous_customer_id,
                 ownership, customer_id, actor_id, source)
            VALUES (NEW.id, old_category, old_customer, NEW.ownership,
                NEW.customer_id,
                nullif(current_setting('atelier.ownership_actor_id', true), '')::integer,
                CASE WHEN TG_OP = 'INSERT' THEN 'created' ELSE 'changed' END);
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER instrument_ownership_history AFTER INSERT OR UPDATE OF ownership, customer_id ON instrument FOR EACH ROW EXECUTE FUNCTION record_instrument_ownership()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER instrument_ownership_history ON instrument")
    op.execute("DROP FUNCTION record_instrument_ownership()")
    op.drop_table("instrument_ownership_event")
    op.drop_index("ix_instrument_ownership", table_name="instrument")
    op.drop_constraint("ck_instrument_owner_category", "instrument", type_="check")
    op.drop_constraint("ck_instrument_ownership", "instrument", type_="check")
    op.drop_column("instrument", "ownership")
