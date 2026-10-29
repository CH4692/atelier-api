"""Provide authentication checks for trusted session and CLI adapters.

This module does not issue tokens or store sessions. UserIdentity must never be
accepted as unverified client input; a session adapter must establish authenticity.
"""

from dataclasses import dataclass
from secrets import token_urlsafe

from pydantic import ValidationError
from sqlmodel import Session, select

from .models import User
from .passwords import hash_password, verify_password
from .roles import UserRole
from .schemas import UserBase

_dummy_hash = hash_password(token_urlsafe(32))


@dataclass(frozen=True)
class UserIdentity:
    """Capture account ID and revocation version after successful verification."""

    user_id: int
    auth_version: int


def authenticate_user(
    email: str, password: str, session: Session, *, allow_customer: bool = False
) -> UserIdentity | None:
    """Verify credentials without creating an authenticated session.

    Customer accounts require the explicit portal flag and a linked customer.
    Workshop authorization is enforced separately by the calling adapter.
    """
    try:
        normalized = UserBase(email=email).email
    except ValidationError:
        verify_password(password, _dummy_hash)
        return None
    user = session.exec(
        select(User)
        .where(User.email == normalized)
        .execution_options(populate_existing=True)
    ).first()
    encoded = user.hashed_password if user is not None else _dummy_hash
    valid = verify_password(password, encoded)
    if (
        not valid
        or user is None
        or not user.is_active
        or (
            user.role == UserRole.CUSTOMER
            and (not allow_customer or user.customer_id is None)
        )
    ):
        return None
    assert user.id is not None
    return UserIdentity(user.id, user.auth_version)


def require_active_user(identity: UserIdentity, session: Session) -> User:
    """Revalidate account state and revocation version on every authorized action.

    Raises:
        PermissionError: If the identity is revoked, inactive, missing or a
            customer-portal account unsupported by workshop authentication.
    """
    user = session.get(User, identity.user_id, populate_existing=True)
    if (
        user is None
        or not user.is_active
        or user.auth_version != identity.auth_version
        or user.role == UserRole.CUSTOMER
    ):
        raise PermissionError("Account identity is inactive or revoked")
    return user
