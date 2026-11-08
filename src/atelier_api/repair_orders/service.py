"""Compose repair history in batches without loading document contents."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlmodel import Session, col

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event
from atelier_api.customers.models import Customer
from atelier_api.instruments.models import Instrument

from .models import RepairDocument, RepairOrder
from .schemas import (
    RepairDocumentRead,
    RepairOrderDetail,
    RepairOrderRead,
    RepairOrderRegister,
    RepairOrderUpdate,
)
from .statuses import RepairStatus, validate_transition


def repair_details(
    session: Session, orders: list[RepairOrder]
) -> list[RepairOrderDetail]:
    """Read metadata for a page of repairs in one query, avoiding binary/N+1 loads."""
    if not orders:
        return []
    ids = [order.id for order in orders]
    rows = (
        session.execute(
            select(
                col(RepairDocument.id),
                col(RepairDocument.repair_order_id),
                col(RepairDocument.filename),
                col(RepairDocument.size_bytes),
                col(RepairDocument.sha256),
                col(RepairDocument.created_at),
            )
            .where(col(RepairDocument.repair_order_id).in_(ids))
            .order_by(col(RepairDocument.created_at), col(RepairDocument.id))
        )
        .mappings()
        .all()
    )
    documents: dict[int, list[RepairDocumentRead]] = {}
    for row in rows:
        metadata = RepairDocumentRead.model_validate(row)
        documents.setdefault(metadata.repair_order_id, []).append(metadata)
    details = []
    for order in orders:
        assert order.id is not None
        details.append(
            RepairOrderDetail(
                **RepairOrderRead.model_validate(order).model_dump(),
                documents=documents.get(order.id, []),
            )
        )
    return details


def persist_order(session: Session, order: RepairOrder) -> RepairOrderRead:
    """Commit the order and creation audit in one transaction."""
    session.add(order)
    session.flush()
    record_event(
        session,
        AuditAction.REPAIR_ORDER_CREATED,
        AuditResource.REPAIR_ORDER,
        order.id,
        actor_id=session.info.get("audit_actor_id"),
    )
    session.commit()
    session.refresh(order)
    return RepairOrderRead.model_validate(order)


def register_order(session: Session, data: RepairOrderRegister) -> RepairOrderRead:
    """Keep customer/instrument references stable without assuming ownership."""
    customer = session.execute(
        select(Customer).where(col(Customer.id) == data.customer_id).with_for_update()
    ).scalar_one_or_none()
    if customer is None:
        raise HTTPException(404, "Customer not found")
    instrument = session.execute(
        select(Instrument)
        .where(col(Instrument.id) == data.instrument_id)
        .with_for_update()
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(404, "Instrument not found")
    return persist_order(
        session, RepairOrder(**data.model_dump(), status_updated_at=data.accepted_at)
    )


def update_order(
    session: Session, repair_id: int, data: RepairOrderUpdate
) -> RepairOrderRead:
    """Serialize partial updates and commit changes with a content-free audit."""
    order = session.execute(
        select(RepairOrder).where(col(RepairOrder.id) == repair_id).with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Repair order not found")
    changes = {
        name: value
        for name, value in data.model_dump(exclude_unset=True).items()
        if getattr(order, name) != value
    }
    if changes:
        details = AuditDetails.model_validate(
            {
                "changed_fields": sorted(changes),
                **(
                    {
                        "previous_expected_completion_date": order.expected_completion_date,
                        "new_expected_completion_date": changes[
                            "expected_completion_date"
                        ],
                    }
                    if "expected_completion_date" in changes
                    else {}
                ),
            }
        )
        order.sqlmodel_update(changes)
        session.add(order)
        record_event(
            session,
            AuditAction.REPAIR_ORDER_UPDATED,
            AuditResource.REPAIR_ORDER,
            order.id,
            actor_id=session.info.get("audit_actor_id"),
            details=details,
        )
        session.commit()
        session.refresh(order)
    return RepairOrderRead.model_validate(order)


def change_status(
    session: Session, repair_id: int, target: RepairStatus
) -> RepairOrderRead:
    """Serialize changes so validation uses the latest committed state.

    Duplicate requests are no-ops, including retries of terminal states. Audit
    failure rolls back both the status and its timestamp with the request session.
    """
    order = session.execute(
        select(RepairOrder)
        .where(col(RepairOrder.id) == repair_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Repair order not found")
    try:
        validate_transition(order.status, target)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    if order.status != target:
        previous = order.status
        order.status = target
        # A backwards wall-clock adjustment must not move the recorded time backwards.
        order.status_updated_at = max(
            datetime.now(UTC),
            order.status_updated_at
            or order.accepted_at
            or datetime.min.replace(tzinfo=UTC),
        )
        session.add(order)
        record_event(
            session,
            AuditAction.REPAIR_STATUS_CHANGED,
            AuditResource.REPAIR_ORDER,
            order.id,
            actor_id=session.info.get("audit_actor_id"),
            details=AuditDetails(previous_status=previous, new_status=target),
        )
        session.commit()
        session.refresh(order)
    return RepairOrderRead.model_validate(order)
