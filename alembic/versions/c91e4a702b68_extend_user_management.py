"""Add roles, UTC timestamps, customer links and provisioning controls.

Revision ID: c91e4a702b68
Revises: b75d90ae3214
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c91e4a702b68"
down_revision: str | Sequence[str] | None = "b75d90ae3214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Extend accounts without changing existing customers or instruments."""
    op.drop_constraint("uq_app_user_email", "app_user", type_="unique")
    op.drop_constraint("ck_app_user_normalized_email", "app_user", type_="check")
    op.create_check_constraint("ck_app_user_email_not_blank", "app_user", "email = btrim(email) AND length(email) > 0")
    op.create_index("uq_app_user_email", "app_user", [sa.text("lower(email)")], unique=True)
    op.add_column("app_user", sa.Column("role", sa.String(8), server_default="employee", nullable=False))
    op.add_column("app_user", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("app_user", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False))
    op.add_column("app_user", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False))
    op.add_column("app_user", sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint("ck_app_user_role", "app_user", "role IN ('admin', 'employee', 'customer')")
    op.create_check_constraint("ck_app_user_auth_version", "app_user", "auth_version >= 0")
    op.create_foreign_key("fk_app_user_customer_id", "app_user", "customer", ["customer_id"], ["id"], ondelete="SET NULL")
    op.create_unique_constraint("uq_app_user_customer_id", "app_user", ["customer_id"])
    op.create_index("ix_app_user_active_role", "app_user", ["role", "is_active"])
    op.create_table(
        "user_provisioning_state",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("bootstrap_completed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_user_provisioning_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO user_provisioning_state (id, bootstrap_completed) VALUES (1, false)")
    op.execute("""
        CREATE FUNCTION update_app_user_security_state() RETURNS trigger AS $$
        DECLARE
            removing_admin boolean := false;
        BEGIN
            IF OLD.role = 'admin' AND OLD.is_active THEN
                IF TG_OP = 'DELETE' THEN
                    removing_admin := true;
                ELSE
                    removing_admin := NEW.role <> 'admin' OR NOT NEW.is_active;
                END IF;
                IF removing_admin THEN
                    PERFORM id FROM user_provisioning_state WHERE id = 1 FOR UPDATE;
                    IF NOT EXISTS (SELECT id FROM app_user WHERE role = 'admin' AND is_active AND id <> OLD.id) THEN
                        RAISE EXCEPTION 'The last active administrator must be retained' USING ERRCODE = '23514';
                    END IF;
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            NEW.created_at := OLD.created_at;
            NEW.updated_at := clock_timestamp();
            NEW.auth_version := OLD.auth_version;
            IF (OLD.is_active AND NOT NEW.is_active)
               OR NEW.role IS DISTINCT FROM OLD.role
               OR NEW.hashed_password IS DISTINCT FROM OLD.hashed_password
               OR NEW.customer_id IS DISTINCT FROM OLD.customer_id THEN
                NEW.auth_version := OLD.auth_version + 1;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER app_user_security_state BEFORE UPDATE OR DELETE ON app_user FOR EACH ROW EXECUTE FUNCTION update_app_user_security_state()")


def downgrade() -> None:
    """Retain account credentials and business data while removing new metadata."""
    op.execute("DROP TRIGGER app_user_security_state ON app_user")
    op.execute("DROP FUNCTION update_app_user_security_state()")
    op.drop_table("user_provisioning_state")
    op.drop_index("ix_app_user_active_role", table_name="app_user")
    op.drop_constraint("uq_app_user_customer_id", "app_user", type_="unique")
    op.drop_constraint("fk_app_user_customer_id", "app_user", type_="foreignkey")
    op.drop_constraint("ck_app_user_role", "app_user", type_="check")
    op.drop_constraint("ck_app_user_auth_version", "app_user", type_="check")
    for name in ("auth_version", "updated_at", "created_at", "customer_id", "role"):
        op.drop_column("app_user", name)
    op.execute("UPDATE app_user SET email = lower(email)")
    op.drop_index("uq_app_user_email", table_name="app_user")
    op.drop_constraint("ck_app_user_email_not_blank", "app_user", type_="check")
    op.create_unique_constraint("uq_app_user_email", "app_user", ["email"])
    op.create_check_constraint("ck_app_user_normalized_email", "app_user", "email = lower(email) AND email = btrim(email) AND length(email) > 0")
