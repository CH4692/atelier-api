"""Persist audit facts independently of the lifetime of accounts and resources."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class AuditAction(StrEnum):
    """Enumerate application-controlled actions rather than accepting request text."""

    CUSTOMER_CREATED = "customer.created"
    CUSTOMER_UPDATED = "customer.updated"
    CUSTOMER_DELETED = "customer.deleted"
    INSTRUMENT_CREATED = "instrument.created"
    INSTRUMENT_UPDATED = "instrument.updated"
    INSTRUMENT_DELETED = "instrument.deleted"
    USER_BOOTSTRAPPED = "user.bootstrapped"
    USER_CREATED = "user.created"
    USER_ACTIVATED = "user.activated"
    USER_DEACTIVATED = "user.deactivated"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_CUSTOMER_CHANGED = "user.customer_association_changed"
    USER_DELETED = "user.deleted"
    USER_SESSIONS_REVOKED = "user.sessions_revoked"
    LOGIN = "auth.login"
    LOGIN_THROTTLED = "auth.login_throttled"
    LOGOUT = "auth.logout"
    SESSION_REVOKED = "auth.session_revoked"
    ADMIN_DENIED = "user.administration_denied"
    SESSION_CLEANUP = "auth.cleanup"
    SESSION_REJECTED = "auth.session_rejected"
    WORKSHOP_DENIED = "auth.workshop_access_denied"
    AUDIT_DENIED = "audit.access_denied"
    RETENTION = "audit.retention"


class AuditResource(StrEnum):
    """Identify resource categories without retaining resource contents."""

    CUSTOMER = "customer"
    INSTRUMENT = "instrument"
    USER = "user"
    SESSION = "session"
    AUDIT = "audit"


class AuditEvent(SQLModel, table=True):
    """Keep identifiers after account deletion without copying personal details.

    Actor and resource identifiers deliberately have no cascading foreign keys.
    They are historical references, not authorization credentials.
    """

    __tablename__: ClassVar[str] = "audit_event"
    id: int | None = Field(default=None, primary_key=True)
    action: str = Field(max_length=80, index=True)
    resource_type: str = Field(max_length=40, index=True)
    resource_id: int | None = Field(default=None, index=True)
    actor_id: int | None = Field(default=None, index=True)
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=DateTime(timezone=True),
        index=True,
    )
    succeeded: bool
    details: dict[str, str | int | None] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
