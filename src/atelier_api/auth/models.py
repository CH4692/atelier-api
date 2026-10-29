"""Persist hashed session tokens and shared login-attempt counters."""

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import CheckConstraint, DateTime
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class UserSession(SQLModel, table=True):
    """Store session verifiers without retaining the browser's raw token."""

    __tablename__: ClassVar[str] = "user_session"
    __table_args__ = (
        CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name="ck_user_session_token_hash"
        ),
        CheckConstraint("expires_at > created_at", name="ck_user_session_expiration"),
    )
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", ondelete="CASCADE", index=True)
    token_hash: str = Field(
        max_length=64, unique=True, index=True, exclude=True, repr=False
    )
    auth_version: int
    created_at: datetime = Field(default_factory=_now, sa_type=DateTime(timezone=True))
    last_activity_at: datetime = Field(
        default_factory=_now, sa_type=DateTime(timezone=True), index=True
    )
    expires_at: datetime = Field(sa_type=DateTime(timezone=True), index=True)
    revoked_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class LoginRateLimit(SQLModel, table=True):
    """Count attempts atomically across all application processes."""

    __tablename__: ClassVar[str] = "login_rate_limit"
    __table_args__ = (
        CheckConstraint("attempts > 0", name="ck_login_rate_limit_attempts"),
    )
    key_hash: str = Field(max_length=64, primary_key=True, repr=False)
    attempts: int
    window_started_at: datetime = Field(sa_type=DateTime(timezone=True), index=True)
