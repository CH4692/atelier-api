"""Provision accounts through authenticated administrative operations."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from atelier_api.customers.models import Customer

from .authentication import UserIdentity, require_active_user
from .models import User, UserProvisioningState
from .passwords import hash_password
from .roles import UserRole
from .schemas import UserCreate, UserRead


def _lock_provisioning(session: Session) -> UserProvisioningState:
    state = session.exec(
        select(UserProvisioningState)
        .where(UserProvisioningState.id == 1)
        .with_for_update()
    ).one()
    session.refresh(state)
    return state


def _administrator(actor: UserIdentity, session: Session) -> User:
    _lock_provisioning(session)
    user = require_active_user(actor, session)
    if user.role != UserRole.ADMIN:
        raise PermissionError("An active administrator is required")
    return user


def _target(user_id: int, session: Session) -> User:
    user = session.get(User, user_id, populate_existing=True)
    if user is None:
        raise LookupError("User not found")
    return user


def _protect_last_administrator(user: User, session: Session) -> None:
    if user.is_active and user.role == UserRole.ADMIN:
        other = session.exec(
            select(User.id).where(
                col(User.is_active).is_(True),
                User.role == UserRole.ADMIN,
                User.id != user.id,
            )
        ).first()
        if other is None:
            raise ValueError(
                "The last active administrator cannot be deactivated, demoted or removed"
            )


def _check_customer(customer_id: int | None, session: Session) -> None:
    if customer_id is not None and (
        customer_id <= 0 or session.get(Customer, customer_id) is None
    ):
        raise LookupError("Customer not found")


def _commit(user: User, session: Session) -> UserRead:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        # Do not expose SQL parameters, which could contain password hashes.
        raise ValueError(
            "Account email or customer association is already used, or account data violates a constraint"
        ) from None
    session.refresh(user)
    return UserRead.model_validate(user)


def _new_user(data: UserCreate, role: UserRole, customer_id: int | None) -> User:
    return User.model_validate(
        {
            "email": data.email,
            "is_active": data.is_active,
            "hashed_password": hash_password(data.password.get_secret_value()),
            "role": role,
            "customer_id": customer_id,
        }
    )


def bootstrap_admin(user: UserCreate, session: Session) -> UserRead:
    """Create the first administrator once through a trusted local operator.

    The singleton row lock prevents concurrent bootstrap. Its persistent latch
    prevents reuse even if all account rows are later removed by a DB operator.

    Raises:
        PermissionError: If bootstrap was completed or an administrator exists.
        ValueError: If the initial administrator is inactive or data conflicts.
    """
    state = _lock_provisioning(session)
    if (
        state.bootstrap_completed
        or session.exec(select(User.id).where(User.role == UserRole.ADMIN)).first()
        is not None
    ):
        raise PermissionError("Administrator bootstrap is permanently closed")
    if not user.is_active:
        raise ValueError("The initial administrator must be active")
    account = _new_user(user, UserRole.ADMIN, None)
    state.bootstrap_completed = True
    session.add(state)
    session.add(account)
    return _commit(account, session)


def create_user(
    user: UserCreate,
    session: Session,
    *,
    actor: UserIdentity,
    role: UserRole = UserRole.EMPLOYEE,
    customer_id: int | None = None,
) -> UserRead:
    """Create an account as an active administrator, defaulting to employee.

    Roles and customer associations are administrative arguments, not fields
    accepted by UserCreate. Email matching never establishes an association.
    """
    _administrator(actor, session)
    role = UserRole(role)
    _check_customer(customer_id, session)
    account = _new_user(user, role, customer_id)
    session.add(account)
    return _commit(account, session)


def set_user_active(
    user_id: int, is_active: bool, session: Session, *, actor: UserIdentity
) -> UserRead:
    """Activate or deactivate an account through an authorized administrator.

    The database increments auth_version on deactivation; reactivation retains
    that version so identities from before deactivation remain revoked.
    """
    _administrator(actor, session)
    user = _target(user_id, session)
    if not is_active:
        _protect_last_administrator(user, session)
    user.is_active = is_active
    session.add(user)
    return _commit(user, session)


def set_user_role(
    user_id: int, role: UserRole, session: Session, *, actor: UserIdentity
) -> UserRead:
    """Change another user's role as administrator and revoke old identities.

    Self role changes are forbidden even for administrators.
    """
    _administrator(actor, session)
    if actor.user_id == user_id:
        raise PermissionError("Users cannot change their own roles")
    user = _target(user_id, session)
    role = UserRole(role)
    if role != UserRole.ADMIN:
        _protect_last_administrator(user, session)
    user.role = role
    session.add(user)
    return _commit(user, session)


def set_customer_association(
    user_id: int, customer_id: int | None, session: Session, *, actor: UserIdentity
) -> UserRead:
    """Link or unlink an account explicitly through an administrator."""
    _administrator(actor, session)
    _check_customer(customer_id, session)
    user = _target(user_id, session)
    user.customer_id = customer_id
    session.add(user)
    return _commit(user, session)


def delete_user(user_id: int, session: Session, *, actor: UserIdentity) -> None:
    """Remove an account as administrator while retaining business records."""
    _administrator(actor, session)
    user = _target(user_id, session)
    _protect_last_administrator(user, session)
    session.delete(user)
    session.commit()
