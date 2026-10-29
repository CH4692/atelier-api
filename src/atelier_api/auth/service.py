"""Manage opaque sessions, expiration and shared login throttling."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import ceil
from re import fullmatch
from secrets import token_urlsafe

from fastapi import HTTPException
from sqlalchemy import case, delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from atelier_api.settings import Settings
from atelier_api.users.authentication import authenticate_user
from atelier_api.users.models import User
from atelier_api.users.roles import UserRole

from .models import LoginRateLimit, UserSession

logger = logging.getLogger("atelier_api.authentication")


def utc_now() -> datetime:
    """Return the current timezone-aware UTC instant."""
    return datetime.now(UTC)


def token_digest(token: str) -> str:
    """Derive a one-way verifier for a cryptographically random token."""
    return sha256(token.encode()).hexdigest()


def valid_token_shape(token: str) -> bool:
    """Limit lookups to the exact format generated from 32 random bytes."""
    return fullmatch(r"[A-Za-z0-9_-]{43}", token) is not None


@dataclass
class IssuedSession:
    """Carry the cookie secret internally without including it in repr or JSON."""

    user: User
    token: str = field(repr=False)
    expires_at: datetime


def _consume_limit(key: str, limit: int, config: Settings, session: Session) -> None:
    now = utc_now()
    cutoff = now - timedelta(seconds=config.login_window_seconds)
    expired = col(LoginRateLimit.window_started_at) <= cutoff
    statement = insert(LoginRateLimit).values(
        key_hash=token_digest(key), attempts=1, window_started_at=now
    )
    throttled = statement.on_conflict_do_update(
        index_elements=[LoginRateLimit.key_hash],
        set_={
            "attempts": case((expired, 1), else_=col(LoginRateLimit.attempts) + 1),
            "window_started_at": case(
                (expired, now), else_=col(LoginRateLimit.window_started_at)
            ),
        },
    ).returning(col(LoginRateLimit.attempts), col(LoginRateLimit.window_started_at))
    row = session.execute(throttled).one()
    session.commit()
    if row.attempts > limit:
        logger.warning("auth_login_throttled")
        retry = max(
            1,
            ceil(
                (
                    row.window_started_at
                    + timedelta(seconds=config.login_window_seconds)
                    - now
                ).total_seconds()
            ),
        )
        raise HTTPException(
            429, "Too many login attempts", headers={"Retry-After": str(retry)}
        )


def revoke_session(token: str | None, session: Session) -> None:
    """Revoke a known cookie verifier without revealing whether it existed."""
    if token and valid_token_shape(token):
        session.execute(
            update(UserSession)
            .where(
                col(UserSession.token_hash) == token_digest(token),
                col(UserSession.revoked_at).is_(None),
            )
            .values(revoked_at=utc_now())
        )
    session.commit()


def login(
    email: str,
    password: str,
    ip: str,
    config: Settings,
    session: Session,
    old_token: str | None = None,
) -> IssuedSession:
    """Verify credentials after atomically charging shared IP and account budgets.

    Successful attempts also consume the budget, preventing rate-limit resets
    from being used to bypass throttling. Account keys never depend on existence.
    """
    _consume_limit("ip:" + ip, config.login_ip_limit, config, session)
    _consume_limit(
        "account:" + email.strip().lower(), config.login_account_limit, config, session
    )
    identity = authenticate_user(
        email, password, session, allow_customer=config.customer_portal_auth_enabled
    )
    if identity is None:
        logger.warning("auth_login_failed")
        raise HTTPException(401, "Invalid credentials")
    user = session.get(User, identity.user_id, populate_existing=True)
    assert user is not None
    if old_token:
        revoke_session(old_token, session)
    token = token_urlsafe(32)
    now = utc_now()
    expires = now + timedelta(seconds=config.session_absolute_seconds)
    session.add(
        UserSession(
            user_id=identity.user_id,
            token_hash=token_digest(token),
            auth_version=identity.auth_version,
            created_at=now,
            last_activity_at=now,
            expires_at=expires,
        )
    )
    session.commit()
    logger.info("auth_login_succeeded")
    return IssuedSession(user, token, expires)


def resolve_session(
    token: str | None, config: Settings, session: Session
) -> tuple[UserSession, User]:
    """Reject missing, expired, revoked or stale sessions using live account state."""
    denied = HTTPException(401, "Authentication required")
    if not token or not valid_token_shape(token):
        raise denied
    record = session.exec(
        select(UserSession)
        .where(UserSession.token_hash == token_digest(token))
        .with_for_update()
    ).first()
    now = utc_now()
    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at <= now
        or record.last_activity_at + timedelta(seconds=config.session_idle_seconds)
        <= now
    ):
        raise denied
    user = session.get(User, record.user_id, populate_existing=True)
    if (
        user is None
        or not user.is_active
        or user.auth_version != record.auth_version
        or (
            user.role == UserRole.CUSTOMER
            and (not config.customer_portal_auth_enabled or user.customer_id is None)
        )
    ):
        raise denied
    return record, user


def cleanup_expired_sessions(session: Session, config: Settings) -> int:
    """Remove expired/revoked sessions and obsolete shared rate-limit counters."""
    now = utc_now()
    ids = session.execute(
        delete(UserSession)
        .where(
            col(UserSession.revoked_at).is_not(None)
            | (col(UserSession.expires_at) <= now)
            | (
                col(UserSession.last_activity_at)
                <= now - timedelta(seconds=config.session_idle_seconds)
            )
        )
        .returning(col(UserSession.id))
    ).all()
    session.execute(
        delete(LoginRateLimit).where(
            col(LoginRateLimit.window_started_at)
            <= now - timedelta(seconds=config.login_window_seconds)
        )
    )
    session.commit()
    return len(ids)
