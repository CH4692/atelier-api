"""Normalize existing customer fields and constrain future writes.

Revision ID: a42d73e15b90
Revises: f31b62d04a89
"""

import sqlalchemy as sa

from alembic import op

revision: str = "a42d73e15b90"
down_revision: str | None = "f31b62d04a89"
branch_labels: str | None = None
depends_on: str | None = None

WHITESPACE = r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"


def upgrade() -> None:
    # No records are deleted or truncated. Invalid legacy data aborts the entire
    # PostgreSQL migration transaction and must be corrected by the operator.
    op.alter_column("customer", "email", nullable=True)
    op.execute(
        f"UPDATE customer SET first_name = btrim(first_name, {WHITESPACE}), last_name = btrim(last_name, {WHITESPACE}), email = nullif(btrim(email, {WHITESPACE}), ''), phone = nullif(btrim(phone, {WHITESPACE}), '')"
    )
    op.execute(
        r"UPDATE customer SET phone = regexp_replace(phone, '[[:space:]()./\-]', '', 'g') WHERE phone IS NOT NULL"
    )
    op.execute(
        "UPDATE customer SET phone = '+' || substring(phone FROM 3) WHERE phone LIKE '00%'"
    )
    for name in ("first_name", "last_name"):
        op.create_check_constraint(
            f"ck_customer_{name}_normalized",
            "customer",
            f"{name} <> '' AND {name} = btrim({name}, {WHITESPACE})",
        )
        op.alter_column("customer", name, type_=sa.String(100))
    op.create_check_constraint(
        "ck_customer_phone_normalized",
        "customer",
        r"phone IS NULL OR phone ~ '^(\+[1-9][0-9]{2,14}|[0-9]{3,15})$'",
    )
    op.create_check_constraint(
        "ck_customer_email_not_blank",
        "customer",
        "email IS NULL OR (email <> '' AND email = btrim(email))",
    )
    op.alter_column("customer", "email", type_=sa.String(254))
    op.alter_column("customer", "phone", type_=sa.String(16))


def downgrade() -> None:
    # Restoring NOT NULL is impossible without inventing personal data.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM customer WHERE email IS NULL) THEN RAISE EXCEPTION 'Cannot downgrade: customers without email exist'; END IF; END $$"
    )
    for name in (
        "first_name_normalized",
        "last_name_normalized",
        "phone_normalized",
        "email_not_blank",
    ):
        op.drop_constraint(f"ck_customer_{name}", "customer", type_="check")
    for name in ("first_name", "last_name", "email", "phone"):
        op.alter_column("customer", name, type_=sa.String())
    op.alter_column("customer", "email", nullable=False)
