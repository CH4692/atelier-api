"""Add hashed browser sessions and shared login rate limits.

Revision ID: d03a8f762c11
Revises: c91e4a702b68
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d03a8f762c11"
down_revision: str | Sequence[str] | None = "c91e4a702b68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create persistent session verifiers and process-shared rate counters."""
    op.create_table(
        "user_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name="ck_user_session_token_hash"
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_user_session_expiration"
        ),
    )
    op.create_index(
        "ix_user_session_token_hash", "user_session", ["token_hash"], unique=True
    )
    for name in ("user_id", "last_activity_at", "expires_at"):
        op.create_index(f"ix_user_session_{name}", "user_session", [name])
    op.create_table(
        "login_rate_limit",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts > 0", name="ck_login_rate_limit_attempts"),
    )
    op.create_index(
        "ix_login_rate_limit_window_started_at",
        "login_rate_limit",
        ["window_started_at"],
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION update_app_user_security_state() RETURNS trigger AS $$
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
                UPDATE user_session SET revoked_at = clock_timestamp() WHERE user_id = OLD.id AND revoked_at IS NULL;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)


def downgrade() -> None:
    """Remove sessions and restore the previous account security trigger."""
    op.execute("""
        CREATE OR REPLACE FUNCTION update_app_user_security_state() RETURNS trigger AS $$
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
    op.drop_table("login_rate_limit")
    op.drop_table("user_session")
