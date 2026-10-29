"""Provision accounts through authenticated administrative operations."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event
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


def _commit(
    user: User,
    session: Session,
    *,
    action: AuditAction | None,
    actor_id: int | None = None,
    details: AuditDetails | None = None,
    revoke: bool = False,
) -> UserRead:
    try:
        session.flush()
        if action is not None:
            record_event(
                session,
                action,
                AuditResource.USER,
                user.id,
                actor_id=actor_id,
                details=details,
            )
        if revoke:
            record_event(
                session,
                AuditAction.USER_SESSIONS_REVOKED,
                AuditResource.USER,
                user.id,
                actor_id=actor_id,
            )
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
    return _commit(account, session, action=AuditAction.USER_BOOTSTRAPPED)


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
    return _commit(
        account,
        session,
        action=AuditAction.USER_CREATED,
        actor_id=actor.user_id,
        details=AuditDetails(
            new_role=account.role, new_customer_id=account.customer_id
        ),
    )


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
    changed = user.is_active != is_active
    user.is_active = is_active
    session.add(user)
    action = AuditAction.USER_ACTIVATED if is_active else AuditAction.USER_DEACTIVATED
    return _commit(
        user,
        session,
        action=action if changed else None,
        actor_id=actor.user_id,
        details=AuditDetails(new_role=user.role),
        revoke=changed and not is_active,
    )


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
    previous_role = user.role
    user.role = role
    session.add(user)
    return _commit(
        user,
        session,
        action=AuditAction.USER_ROLE_CHANGED if previous_role != role else None,
        actor_id=actor.user_id,
        revoke=previous_role != role,
        details=AuditDetails(previous_role=previous_role, new_role=role),
    )


def set_customer_association(
    user_id: int, customer_id: int | None, session: Session, *, actor: UserIdentity
) -> UserRead:
    """Link or unlink an account explicitly through an administrator."""
    _administrator(actor, session)
    _check_customer(customer_id, session)
    user = _target(user_id, session)
    previous_customer_id = user.customer_id
    user.customer_id = customer_id
    session.add(user)
    return _commit(
        user,
        session,
        action=AuditAction.USER_CUSTOMER_CHANGED
        if previous_customer_id != customer_id
        else None,
        actor_id=actor.user_id,
        revoke=previous_customer_id != customer_id,
        details=AuditDetails(
            previous_customer_id=previous_customer_id, new_customer_id=customer_id
        ),
    )


def delete_user(user_id: int, session: Session, *, actor: UserIdentity) -> None:
    """Remove an account as administrator while retaining business records."""
    _administrator(actor, session)
    user = _target(user_id, session)
    _protect_last_administrator(user, session)
    record_event(
        session,
        AuditAction.USER_DELETED,
        AuditResource.USER,
        user.id,
        actor_id=actor.user_id,
    )
    record_event(
        session,
        AuditAction.USER_SESSIONS_REVOKED,
        AuditResource.USER,
        user.id,
        actor_id=actor.user_id,
    )
    session.delete(user)
    session.commit()


def audit_customer_removal(customer_id: int, session: Session) -> None:
    """Record the account effects of an authorized customer deletion.

    PostgreSQL clears these associations and revokes sessions through its existing
    foreign key/security trigger. Keep the audit facts in the deleting transaction.
    This helper does not change accounts or authorize customer deletion itself.
    """
    users = session.exec(
        select(User).where(User.customer_id == customer_id).with_for_update()
    ).all()
    for user in users:
        record_event(
            session,
            AuditAction.USER_CUSTOMER_CHANGED,
            AuditResource.USER,
            user.id,
            actor_id=session.info.get("audit_actor_id"),
            details=AuditDetails(
                previous_customer_id=customer_id, new_customer_id=None
            ),
        )
        record_event(
            session,
            AuditAction.USER_SESSIONS_REVOKED,
            AuditResource.USER,
            user.id,
            actor_id=session.info.get("audit_actor_id"),
        )
