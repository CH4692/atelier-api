"""Persist accounts, provisioning state and revocable authentication versions."""

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Text,
    UniqueConstraint,
    column,
    func,
)
from sqlmodel import Field, SQLModel

from .roles import UserRole
from .schemas import UserBase


def _utc_now() -> datetime:
    return datetime.now(UTC)


class User(UserBase, table=True):
    """Store accounts independently of workshop customers.

    The database trigger maintains updated_at and advances auth_version on
    security-relevant changes. Password hashes are never serialized by default.
    """

    __tablename__: ClassVar[str] = "app_user"
    __table_args__ = (
        Index("uq_app_user_email", func.lower(column("email")), unique=True),
        Index("ix_app_user_active_role", "role", "is_active"),
        UniqueConstraint("customer_id", name="uq_app_user_customer_id"),
        CheckConstraint(
            "email = btrim(email) AND length(email) > 0",
            name="ck_app_user_email_not_blank",
        ),
        CheckConstraint(
            "hashed_password LIKE '$argon2id$%'", name="ck_app_user_password_hash"
        ),
        CheckConstraint("auth_version >= 0", name="ck_app_user_auth_version"),
    )

    id: int | None = Field(default=None, primary_key=True)
    hashed_password: str = Field(sa_type=Text, exclude=True, repr=False)
    role: UserRole = Field(
        default=UserRole.EMPLOYEE,
        sa_type=Enum(
            UserRole,
            native_enum=False,
            create_constraint=True,
            name="ck_app_user_role",
            values_callable=lambda roles: [r.value for r in roles],
        ),
        sa_column_kwargs={"server_default": "employee"},
    )
    customer_id: int | None = Field(
        default=None, foreign_key="customer.id", ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.clock_timestamp()},
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.clock_timestamp()},
    )
    auth_version: int = Field(
        default=0, exclude=True, repr=False, sa_column_kwargs={"server_default": "0"}
    )


class UserProvisioningState(SQLModel, table=True):
    """Serialize privileged changes and permanently seal initial bootstrap."""

    __tablename__: ClassVar[str] = "user_provisioning_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_user_provisioning_singleton"),)
    id: int = Field(
        default=1, primary_key=True, sa_column_kwargs={"autoincrement": False}
    )
    bootstrap_completed: bool = Field(
        default=False, sa_column_kwargs={"server_default": "false"}
    )
