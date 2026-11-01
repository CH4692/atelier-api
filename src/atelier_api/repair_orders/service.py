"""Compose repair history in batches without loading document contents."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlmodel import Session, col

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.service import record_event
from atelier_api.customers.models import Customer
from atelier_api.instruments.models import Instrument

from .models import RepairDocument, RepairOrder
from .schemas import (
    RepairDocumentRead,
    RepairOrderDetail,
    RepairOrderRead,
    RepairOrderRegister,
)


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
    return persist_order(session, RepairOrder(**data.model_dump()))
