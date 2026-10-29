"""Expose secure login, idempotent logout and the authenticated account."""

from fastapi import APIRouter, Depends, Request, Response

from atelier_api.database import SessionDep
from atelier_api.users.schemas import UserRead

from .dependencies import CurrentUser, SecuritySettings, validate_csrf
from .schemas import LoginRequest
from .service import login, revoke_session

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/login",
    summary="Create a secure browser session",
    response_model=UserRead,
    dependencies=[Depends(validate_csrf)],
    responses={
        401: {"description": "Invalid credentials"},
        403: {"description": "CSRF protection failed"},
        429: {"description": "Too many attempts"},
    },
)
def login_endpoint(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    config: SecuritySettings,
    session: SessionDep,
) -> UserRead:
    """Verify credentials and return the account with an opaque HttpOnly cookie.

    Session tokens are included only in Set-Cookie, never in the response JSON.
    Every successful login rotates the current browser session.
    """
    issued = login(
        credentials.email,
        credentials.password.get_secret_value(),
        request.client.host if request.client else "unknown",
        config,
        session,
        request.cookies.get(config.session_cookie_name),
    )
    response.set_cookie(
        config.session_cookie_name,
        issued.token,
        httponly=True,
        secure=config.secure_cookies,
        samesite="lax",
        path="/",
        max_age=config.session_absolute_seconds,
        expires=issued.expires_at,
    )
    return UserRead.model_validate(issued.user)


@router.post(
    "/logout",
    summary="Revoke the current session",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(validate_csrf)],
)
def logout_endpoint(
    request: Request, config: SecuritySettings, session: SessionDep
) -> Response:
    """Revoke the cookie's session and clear it even when already absent or revoked."""
    revoke_session(request.cookies.get(config.session_cookie_name), session)
    response = Response(status_code=204)
    response.delete_cookie(
        config.session_cookie_name,
        httponly=True,
        secure=config.secure_cookies,
        samesite="lax",
        path="/",
    )
    return response


@router.get(
    "/me",
    summary="Get the authenticated account",
    response_model=UserRead,
    responses={401: {"description": "Authentication required"}},
)
def current_account(user: CurrentUser) -> UserRead:
    """Return current account metadata without credentials or session verifiers."""
    return UserRead.model_validate(user)
