"""Import one small profile into an empty, explicitly disposable PostgreSQL DB."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256

from pydantic import SecretStr
from sqlalchemy import Connection, func, literal, text
from sqlalchemy import select as sql_select
from sqlalchemy.engine import URL, make_url
from sqlmodel import Session, SQLModel, select

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event
from atelier_api.auth.models import LoginRateLimit, UserSession
from atelier_api.customers.models import Customer
from atelier_api.estimates.models import RepairEstimate
from atelier_api.estimates.schemas import EstimateApproval, EstimateWrite
from atelier_api.estimates.service import (
    approve_estimate,
    create_estimate,
    transition_estimate,
)
from atelier_api.estimates.statuses import EstimateStatus
from atelier_api.instruments.models import Instrument
from atelier_api.instruments.ownership import set_ownership_actor
from atelier_api.photos.models import InstrumentPhoto
from atelier_api.repair_orders.item_models import RepairItem
from atelier_api.repair_orders.item_schemas import RepairItemCreate
from atelier_api.repair_orders.models import RepairDocument, RepairOrder
from atelier_api.repair_orders.statuses import validate_transition
from atelier_api.repair_templates.models import RepairTemplate
from atelier_api.repair_templates.schemas import RepairTemplateCreate
from atelier_api.settings import Settings
from atelier_api.users.authentication import UserIdentity
from atelier_api.users.models import User, UserProvisioningState
from atelier_api.users.roles import UserRole
from atelier_api.users.schemas import UserCreate
from atelier_api.users.service import bootstrap_admin, create_user

from .data import PREFIX, PROFILE, UNAVAILABLE, WORK, SmallPlan, build_small

# Register security tables for the empty-database guard even outside application imports.
_SECURITY_TABLES = (LoginRateLimit, UserSession)
SEED_LOCK = 718_240_931
INTERNAL_ACCOUNTS = ("meister", "geigenbau", "restaurierung", "service", "pausiert")


@dataclass(frozen=True)
class SeedReport:
    profile: str
    as_of: date
    reused: bool
    counts: dict[str, int]
    limitations: tuple[str, ...] = UNAVAILABLE
    dry_run: bool = False


def guard_target(config: Settings, url: URL | None = None) -> None:
    """Require development mode and a named disposable PostgreSQL database."""
    target = url or make_url(config.database_url)
    if (
        config.environment != "development"
        or target.get_backend_name() != "postgresql"
        or not (target.database or "").endswith(("_demo", "_test"))
    ):
        raise ValueError(
            "Demo seeding requires development mode and a PostgreSQL database ending in _demo or _test."
        )


def _counts(session: Session) -> dict[str, int]:

    result = {}
    for name, model in (
        ("customers", Customer),
        ("instruments", Instrument),
        ("repairs", RepairOrder),
        ("documents", RepairDocument),
        ("users", User),
        ("templates", RepairTemplate),
        ("repair_items", RepairItem),
        ("estimates", RepairEstimate),
        ("photos", InstrumentPhoto),
    ):
        result[name] = session.exec(select(func.count()).select_from(model)).one()
    result["internal_users"] = session.exec(
        select(func.count()).select_from(User).where(User.role != UserRole.CUSTOMER)
    ).one()
    result["portal_users"] = session.exec(
        select(func.count()).select_from(User).where(User.role == UserRole.CUSTOMER)
    ).one()
    result.update(rentals=0, invoices=0, payments=0)
    return result


def _empty(session: Session) -> None:
    state = session.get(UserProvisioningState, 1)
    if state is None or state.bootstrap_completed:
        raise ValueError(
            "The migrated database must have an unused administrator bootstrap latch."
        )
    for table in SQLModel.metadata.sorted_tables:
        if table.name == "user_provisioning_state":
            continue
        if session.execute(sql_select(literal(1)).select_from(table).limit(1)).first():
            raise ValueError(
                "Refusing to mix demo data with existing records. Use a fresh migrated demo database."
            )


def _audit(
    session: Session,
    action: AuditAction,
    resource: AuditResource,
    identifier: int | None,
    actor: int,
    details: AuditDetails | None = None,
) -> None:
    record_event(session, action, resource, identifier, actor_id=actor, details=details)


def _users(session: Session, password: SecretStr, customer_id: int) -> int:
    initial = bootstrap_admin(
        UserCreate(email="meister.demo@example.com", password=password), session
    )
    admin = session.get(User, initial.id)
    assert admin is not None
    actor = UserIdentity(initial.id, admin.auth_version)
    for name in INTERNAL_ACCOUNTS[1:]:
        create_user(
            UserCreate(
                email=f"{name}.demo@example.com",
                password=password,
                is_active=name != "pausiert",
            ),
            session,
            actor=actor,
        )
    create_user(
        UserCreate(email="kunde.demo@example.com", password=password),
        session,
        actor=actor,
        role=UserRole.CUSTOMER,
        customer_id=customer_id,
    )
    session.info["audit_actor_id"] = initial.id
    return initial.id


def _estimates(
    session: Session, order: RepairOrder, line: RepairItemCreate, index: int
) -> None:
    assert order.id is not None
    estimate = create_estimate(session, order.id, EstimateWrite(items=[line]))
    variant = index % 5
    if index >= 110 and variant == 2:
        variant = 1  # Awaiting approval must not already have an approved estimate.
    if variant == 0:
        return
    issued = transition_estimate(session, order.id, estimate.id, EstimateStatus.ISSUED)
    if variant == 2:
        assert issued.issued_at is not None
        approve_estimate(
            session,
            order.id,
            estimate.id,
            EstimateApproval(
                approved_at=issued.issued_at,
                approval_method="in_person",
                approval_reference="Fiktive Demo-Freigabe; keine elektronische Signatur.",
            ),
        )
    elif variant in {3, 4}:
        transition_estimate(
            session,
            order.id,
            estimate.id,
            EstimateStatus.REJECTED if variant == 3 else EstimateStatus.WITHDRAWN,
        )


def _populate(session: Session, plan: SmallPlan, password: SecretStr) -> None:
    customers = [
        Customer.model_validate(spec.data.model_dump() | {"is_archived": spec.archived})
        for spec in plan.customers
    ]
    session.add_all(customers)
    session.flush()
    first_customer_id = customers[0].id
    assert first_customer_id is not None
    actor = _users(session, password, first_customer_id)
    instruments = []
    for spec in plan.instruments:
        values = spec.data.model_dump()
        values["customer_id"] = (
            customers[spec.customer_index].id
            if spec.customer_index is not None
            else None
        )
        instrument = Instrument.model_validate(values | {"is_archived": spec.archived})
        set_ownership_actor(session)
        session.add(instrument)
        session.flush()
        instruments.append(instrument)
        _audit(
            session,
            AuditAction.INSTRUMENT_CREATED,
            AuditResource.INSTRUMENT,
            instrument.id,
            actor,
        )
    for description, price in WORK:
        data = RepairTemplateCreate(
            name=description, description=description, default_unit_price=Decimal(price)
        )
        session.add(RepairTemplate.model_validate(data.model_dump()))
    orders = []
    for index, repair_spec in enumerate(plan.repairs):
        values = repair_spec.data.model_dump()
        values.update(
            instrument_id=instruments[repair_spec.instrument_index].id,
            customer_id=customers[repair_spec.customer_index].id,
            created_at=repair_spec.created_at,
            status_updated_at=repair_spec.data.accepted_at,
            performed_at=None,
        )
        order = RepairOrder.model_validate(values)
        session.add(order)
        session.flush()
        orders.append(order)
        assert order.id is not None
        _audit(
            session,
            AuditAction.REPAIR_ORDER_CREATED,
            AuditResource.REPAIR_ORDER,
            order.id,
            actor,
        )
        session.add(
            RepairItem(repair_order_id=order.id, **repair_spec.line.model_dump())
        )
        if index % 5 < 2:
            material = RepairItemCreate(
                kind="material",
                description="Material für die dokumentierte Werkstattarbeit",
                quantity=Decimal("1.000"),
                unit_price=Decimal("18.50") + Decimal(index % 9),
            )
            session.add(RepairItem(repair_order_id=order.id, **material.model_dump()))
        # Estimate services retain their existing authorization, revision and approval rules.
        if 95 <= index < 120:
            _estimates(session, order, repair_spec.line, index)
        for target, occurred in repair_spec.history[1:]:
            previous = order.status
            validate_transition(previous, target)
            order.status, order.status_updated_at = target, occurred
            _audit(
                session,
                AuditAction.REPAIR_STATUS_CHANGED,
                AuditResource.REPAIR_ORDER,
                order.id,
                actor,
                AuditDetails(previous_status=previous, new_status=target),
            )
        order.performed_at = repair_spec.data.performed_at
        order.is_archived = repair_spec.archived
        session.add(order)
    session.flush()
    for index in range(30):
        order = orders[index * 5]
        assert order.id is not None
        content = (
            f"FIKTIVER DEMOBELEG – Werkstatt Klanggarten\nAuftrag {order.id}\n{order.work_description}\nStatus: {order.status.value}\nKeine Rechnung, kein Zahlungsbeleg und keine reale Kundendokumentation.\n"
        ).encode()
        session.add(
            RepairDocument(
                repair_order_id=order.id,
                filename=f"Werkstattbericht-{index + 1:02}.txt",
                size_bytes=len(content),
                sha256=sha256(content).hexdigest(),
                content=content,
                created_at=order.status_updated_at or order.created_at,
            )
        )
    # The marker is committed atomically with the complete dataset, never as a partial checkpoint.
    instruments[
        0
    ].notes = f"{PROFILE};as_of={plan.as_of.isoformat()}\n{instruments[0].notes}"
    session.add(instruments[0])
    session.commit()


def seed_small(
    connection: Connection,
    config: Settings,
    *,
    password: SecretStr | None,
    as_of: date | None = None,
) -> SeedReport:
    """Seed inside a caller-owned transaction; caller must roll it back on failure.

    Nested service commits release savepoints, never the outer seed transaction.
    Existing marked data is reported without resetting edits or changing passwords.
    """
    guard_target(config)
    guard_target(config, connection.engine.url)
    if not connection.in_transaction():
        raise ValueError("An outer transaction is required for atomic demo seeding.")
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SEED_LOCK})
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        marker = session.exec(
            select(Instrument).where(
                Instrument.identification_number == f"{PREFIX}0001"
            )
        ).one_or_none()
        if marker is not None and (marker.notes or "").startswith(f"{PROFILE};as_of="):
            recorded = date.fromisoformat(
                (marker.notes or "").splitlines()[0].split("=", 1)[1]
            )
            if as_of is not None and as_of != recorded:
                raise ValueError(
                    "Existing demo data uses another reference date; it will not be rewritten."
                )
            return SeedReport(PROFILE, recorded, True, _counts(session))
        _empty(session)
        if password is None:
            raise ValueError(
                "Supply ARTELIER_DEMO_PASSWORD or an interactive password for new demo accounts."
            )
        # Validate policy before any inserts, with secrets excluded from errors/output.
        UserCreate(email="meister.demo@example.com", password=password)
        from zoneinfo import ZoneInfo

        plan = build_small(as_of or datetime.now(ZoneInfo("Europe/Berlin")).date())
        _populate(session, plan, password)
        return SeedReport(PROFILE, plan.as_of, False, _counts(session))
