from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from atelier_api.customers.models import Customer
from atelier_api.users.authentication import authenticate_user, require_active_user
from atelier_api.users.models import User
from atelier_api.users.passwords import hash_password, verify_password
from atelier_api.users.roles import UserRole
from atelier_api.users.schemas import UserCreate
from atelier_api.users.service import (
    bootstrap_admin,
    create_user,
    delete_user,
    set_customer_association,
    set_user_active,
    set_user_role,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def user_session(db_connection):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        yield session


@pytest.fixture
def administrator(user_session):
    created = bootstrap_admin(
        UserCreate(email="admin@example.com", password="test-password-123"),
        user_session,
    )
    actor = authenticate_user(created.email, "test-password-123", user_session)
    assert actor is not None
    return actor


def test_employee_creation_persists_secure_defaults_and_timestamps(
    user_session, administrator
):
    result = create_user(
        UserCreate(email=" Employee@Example.COM ", password="test-password-123"),
        user_session,
        actor=administrator,
    )
    assert result.id > 0
    assert result.email == "employee@example.com"
    assert result.role is UserRole.EMPLOYEE
    assert result.customer_id is None
    assert result.created_at.utcoffset().total_seconds() == 0
    stored = user_session.get(User, result.id)
    assert stored is not None
    assert verify_password("test-password-123", stored.hashed_password)
    assert not verify_password("wrong-password", stored.hashed_password)
    assert "hashed_password" not in result.model_dump()


def test_database_enforces_case_insensitive_email_uniqueness(
    user_session, administrator
):
    create_user(
        UserCreate(email="employee@example.com", password="test-password-123"),
        user_session,
        actor=administrator,
    )
    with pytest.raises(ValueError, match="already used"):
        create_user(
            UserCreate(email="EMPLOYEE@example.com", password="test-password-123"),
            user_session,
            actor=administrator,
        )
    with pytest.raises(IntegrityError), user_session.begin_nested():
        user_session.execute(
            text(
                "INSERT INTO app_user (email, hashed_password) VALUES (:email, :hash)"
            ),
            {
                "email": "EMPLOYEE@example.com",
                "hash": hash_password("test-password-123"),
            },
        )


def test_admin_assigns_roles_but_cannot_change_own_role(user_session, administrator):
    employee = create_user(
        UserCreate(email="employee@example.com", password="test-password-123"),
        user_session,
        actor=administrator,
    )
    assert (
        set_user_role(
            employee.id, UserRole.ADMIN, user_session, actor=administrator
        ).role
        is UserRole.ADMIN
    )
    with pytest.raises(PermissionError, match="own roles"):
        set_user_role(
            administrator.user_id, UserRole.EMPLOYEE, user_session, actor=administrator
        )
    with pytest.raises(ValueError):
        set_user_role(employee.id, "invalid", user_session, actor=administrator)


def test_employee_cannot_provision_change_roles_or_activate_accounts(
    user_session, administrator
):
    employee = create_user(
        UserCreate(email="employee@example.com", password="test-password-123"),
        user_session,
        actor=administrator,
    )
    identity = authenticate_user(employee.email, "test-password-123", user_session)
    assert identity is not None
    for operation in [
        lambda: create_user(
            UserCreate(email="other@example.com", password="test-password-123"),
            user_session,
            actor=identity,
        ),
        lambda: set_user_role(
            employee.id, UserRole.ADMIN, user_session, actor=identity
        ),
        lambda: set_user_active(employee.id, False, user_session, actor=identity),
        lambda: set_customer_association(
            employee.id, None, user_session, actor=identity
        ),
    ]:
        with pytest.raises(PermissionError):
            operation()


def test_last_active_admin_cannot_be_disabled_deleted_or_demoted(
    user_session, administrator
):
    for operation in [
        lambda: set_user_active(
            administrator.user_id, False, user_session, actor=administrator
        ),
        lambda: delete_user(administrator.user_id, user_session, actor=administrator),
    ]:
        with pytest.raises(ValueError, match="last active administrator"):
            operation()
    for sql in [
        "UPDATE app_user SET is_active=false WHERE id=:id",
        "DELETE FROM app_user WHERE id=:id",
        "UPDATE app_user SET role='employee' WHERE id=:id",
    ]:
        with pytest.raises(IntegrityError), user_session.begin_nested():
            user_session.execute(text(sql), {"id": administrator.user_id})


def test_deactivation_revokes_old_identity_and_reactivation_does_not_restore_it(
    user_session, administrator
):
    employee = create_user(
        UserCreate(email="employee@example.com", password="test-password-123"),
        user_session,
        actor=administrator,
    )
    identity = authenticate_user(employee.email, "test-password-123", user_session)
    assert identity is not None
    stored = user_session.get(User, employee.id)
    original_hash = stored.hashed_password
    original_updated = stored.updated_at
    set_user_active(employee.id, False, user_session, actor=administrator)
    assert authenticate_user(employee.email, "test-password-123", user_session) is None
    with pytest.raises(PermissionError):
        require_active_user(identity, user_session)
    set_user_active(employee.id, True, user_session, actor=administrator)
    with pytest.raises(PermissionError):
        require_active_user(identity, user_session)
    assert (
        authenticate_user(employee.email, "test-password-123", user_session) is not None
    )
    user_session.refresh(stored)
    assert stored.hashed_password == original_hash
    assert stored.updated_at > original_updated


def test_customer_association_is_explicit_unique_and_does_not_enable_portal(
    user_session, administrator
):
    customer = Customer(
        first_name="Maria", last_name="Doe", email="customer@example.com"
    )
    user_session.add(customer)
    user_session.commit()
    user_session.refresh(customer)
    first = create_user(
        UserCreate(email=customer.email, password="test-password-123"),
        user_session,
        actor=administrator,
        role=UserRole.CUSTOMER,
    )
    assert first.customer_id is None
    assert authenticate_user(first.email, "test-password-123", user_session) is None
    linked = set_customer_association(
        first.id, customer.id, user_session, actor=administrator
    )
    assert linked.customer_id == customer.id
    assert authenticate_user(first.email, "test-password-123", user_session) is None
    with pytest.raises(ValueError, match="already used"):
        create_user(
            UserCreate(email="other@example.com", password="test-password-123"),
            user_session,
            actor=administrator,
            customer_id=customer.id,
        )
    with pytest.raises(LookupError):
        set_customer_association(first.id, 999999, user_session, actor=administrator)
    set_customer_association(first.id, None, user_session, actor=administrator)
    assert user_session.get(Customer, customer.id) is not None


def test_bootstrap_is_one_time_and_cannot_be_reopened_by_user_deletion(
    user_session, administrator
):
    with pytest.raises(PermissionError, match="permanently closed"):
        bootstrap_admin(
            UserCreate(email="another-admin@example.com", password="test-password-123"),
            user_session,
        )
    # A trusted DB operator can truncate rows; even that must not reset the latch.
    user_session.execute(text("TRUNCATE app_user CASCADE"))
    user_session.commit()
    with pytest.raises(PermissionError, match="permanently closed"):
        bootstrap_admin(
            UserCreate(email="another-admin@example.com", password="test-password-123"),
            user_session,
        )


def test_invalid_role_is_rejected_by_database(user_session):
    with pytest.raises(IntegrityError), user_session.begin_nested():
        user_session.execute(
            text(
                "INSERT INTO app_user (email, hashed_password, role) VALUES ('invalid@example.com', :hash, 'invalid')"
            ),
            {"hash": hash_password("test-password-123")},
        )


def test_invalid_customer_is_rejected_by_database(user_session):
    with pytest.raises(IntegrityError), user_session.begin_nested():
        user_session.execute(
            text(
                "INSERT INTO app_user (email, hashed_password, customer_id) VALUES ('invalid@example.com', :hash, 999999)"
            ),
            {"hash": hash_password("test-password-123")},
        )


def test_role_changes_revoke_existing_identity(user_session, administrator):
    employee = create_user(
        UserCreate(email="employee@example.com", password="test-password-123"),
        user_session,
        actor=administrator,
    )
    identity = authenticate_user(employee.email, "test-password-123", user_session)
    set_user_role(employee.id, UserRole.ADMIN, user_session, actor=administrator)
    with pytest.raises(PermissionError):
        require_active_user(identity, user_session)
    assert authenticate_user(employee.email, "wrong-password", user_session) is None
    assert (
        authenticate_user("missing@example.com", "test-password-123", user_session)
        is None
    )


def test_user_migration_types_and_constraints(postgres_engine):
    inspector = inspect(postgres_engine)
    columns = {c["name"]: c for c in inspector.get_columns("app_user")}
    assert columns["created_at"]["type"].timezone
    assert columns["updated_at"]["type"].timezone
    assert any(
        index["name"] == "uq_app_user_email" and index["unique"]
        for index in inspector.get_indexes("app_user")
    )
    assert any(
        fk["referred_table"] == "customer"
        for fk in inspector.get_foreign_keys("app_user")
    )
    assert any(
        c["column_names"] == ["customer_id"]
        for c in inspector.get_unique_constraints("app_user")
    )


def test_concurrent_deactivation_keeps_one_active_administrator(postgres_engine):
    try:
        with Session(postgres_engine) as session:
            first = bootstrap_admin(
                UserCreate(email="first@example.com", password="test-password-123"),
                session,
            )
            first_actor = authenticate_user(first.email, "test-password-123", session)
            second = create_user(
                UserCreate(email="second@example.com", password="test-password-123"),
                session,
                actor=first_actor,
                role=UserRole.ADMIN,
            )
            second_actor = authenticate_user(second.email, "test-password-123", session)

        def deactivate_self(actor):
            with Session(postgres_engine) as session:
                try:
                    set_user_active(actor.user_id, False, session, actor=actor)
                    return True
                except ValueError:
                    return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(deactivate_self, [first_actor, second_actor]))
        assert sorted(results) == [False, True]
        with Session(postgres_engine) as session:
            active = session.exec(
                select(User).where(
                    col(User.is_active).is_(True), User.role == UserRole.ADMIN
                )
            ).all()
            assert len(active) == 1
    finally:
        # This fixture owns a disposable schema; reset committed concurrency data.
        with postgres_engine.begin() as connection:
            connection.execute(text("TRUNCATE app_user RESTART IDENTITY CASCADE"))
            connection.execute(
                text(
                    "UPDATE user_provisioning_state SET bootstrap_completed=false WHERE id=1"
                )
            )


def test_revoked_administrator_cannot_resume_privileged_actions_after_reactivation(
    user_session, administrator
):
    other = create_user(
        UserCreate(email="other-admin@example.com", password="test-password-123"),
        user_session,
        actor=administrator,
        role=UserRole.ADMIN,
    )
    other_actor = authenticate_user(other.email, "test-password-123", user_session)
    set_user_active(administrator.user_id, False, user_session, actor=other_actor)
    for reactivate in (False, True):
        if reactivate:
            set_user_active(
                administrator.user_id, True, user_session, actor=other_actor
            )
        with pytest.raises(PermissionError):
            create_user(
                UserCreate(email="blocked@example.com", password="test-password-123"),
                user_session,
                actor=administrator,
            )


def test_inactive_admin_does_not_count_as_remaining_administrator(
    user_session, administrator
):
    create_user(
        UserCreate(
            email="inactive@example.com", password="test-password-123", is_active=False
        ),
        user_session,
        actor=administrator,
        role=UserRole.ADMIN,
    )
    with pytest.raises(ValueError, match="last active administrator"):
        set_user_active(administrator.user_id, False, user_session, actor=administrator)


def test_deleting_account_preserves_associated_business_record(
    user_session, administrator
):
    customer = Customer(
        first_name="Maria", last_name="Doe", email="customer@example.com"
    )
    user_session.add(customer)
    user_session.commit()
    user_session.refresh(customer)
    account = create_user(
        UserCreate(email=customer.email, password="test-password-123"),
        user_session,
        actor=administrator,
        customer_id=customer.id,
    )
    delete_user(account.id, user_session, actor=administrator)
    assert user_session.get(User, account.id) is None
    assert user_session.get(Customer, customer.id) is not None
