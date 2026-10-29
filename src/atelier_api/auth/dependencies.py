"""Centralize session authentication, workshop authorization and CSRF checks."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyCookie

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.service import record_event
from atelier_api.database import SessionDep
from atelier_api.settings import Settings, settings
from atelier_api.users.models import User
from atelier_api.users.roles import UserRole

from .service import resolve_session, utc_now


def security_settings(request: Request) -> Settings:
    """Read security configuration from the application instance."""
    return request.app.state.settings


SecuritySettings = Annotated[Settings, Depends(security_settings)]
_session_cookie_scheme = APIKeyCookie(
    name=settings.session_cookie_name,
    scheme_name="ServerSideSession",
    description="Opaque server-side session cookie created by POST /api/v1/auth/login.",
    auto_error=False,
)
DocumentedSessionCookie = Annotated[str | None, Security(_session_cookie_scheme)]


def require_https(request: Request, config: SecuritySettings) -> None:
    """Fail closed when production requests reach the application over HTTP."""
    if config.secure_cookies and request.url.scheme != "https":
        raise HTTPException(403, "HTTPS required")


def validate_csrf(request: Request, config: SecuritySettings) -> None:
    """Apply the strict-origin/custom-header CSRF strategy to unsafe requests.

    This AJAX strategy relies on exact CORS allowlists and mandatory browser
    preflight for the non-simple header. It does not expose a session token to JS.
    """
    require_https(request, config)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and (
        request.headers.get("origin") not in config.frontend_origins
        or request.headers.get("x-csrf-protection") != "1"
    ):
        raise HTTPException(403, "Request forbidden")


def get_current_user(
    request: Request,
    config: SecuritySettings,
    session: SessionDep,
    _documented_cookie: DocumentedSessionCookie,
) -> User:
    """Authenticate a live server-side session before any protected request."""
    require_https(request, config)
    record, user = resolve_session(
        request.cookies.get(config.session_cookie_name), config, session
    )
    validate_csrf(request, config)
    session.info["audit_actor_id"] = user.id
    record.last_activity_at = utc_now()
    session.add(record)
    session.commit()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_internal_user(user: CurrentUser, session: SessionDep) -> User:
    """Authorize workshop data separately from successful authentication."""
    if user.role not in {UserRole.ADMIN, UserRole.EMPLOYEE}:
        record_event(
            session,
            AuditAction.WORKSHOP_DENIED,
            AuditResource.USER,
            user.id,
            actor_id=user.id,
            succeeded=False,
        )
        session.commit()
        raise HTTPException(403, "Access forbidden")
    return user
