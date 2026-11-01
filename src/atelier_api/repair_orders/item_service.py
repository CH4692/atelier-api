"""Control item edits under the same repair lock used for finalization."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlmodel import Session, col

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event

from .amounts import line_amount, sum_amounts
from .item_models import RepairItem, RepairItemKind
from .item_schemas import (
    RepairItemCreate,
    RepairItemRead,
    RepairItemsRead,
    RepairItemUpdate,
)
from .models import RepairOrder
from .statuses import RepairStatus


def read_item(item: RepairItem) -> RepairItemRead:
    """Build the shared response projection with the central rounding rule."""
    return RepairItemRead(
        **item.model_dump(), line_total=line_amount(item.quantity, item.unit_price)
    )


def list_items(session: Session, repair_id: int) -> RepairItemsRead:
    """Read all positions once so subtotals and total use identical line amounts."""
    if session.get(RepairOrder, repair_id) is None:
        raise HTTPException(404, "Repair order not found")
    rows = (
        session.execute(
            select(RepairItem)
            .where(col(RepairItem.repair_order_id) == repair_id)
            .order_by(col(RepairItem.id))
        )
        .scalars()
        .all()
    )
    items = [read_item(item) for item in rows]
    services = sum_amounts(
        item.line_total for item in items if item.kind == RepairItemKind.SERVICE
    )
    materials = sum_amounts(
        item.line_total for item in items if item.kind == RepairItemKind.MATERIAL
    )
    return RepairItemsRead(
        repair_order_id=repair_id,
        items=items,
        service_total=services,
        material_total=materials,
        total=sum_amounts([services, materials]),
    )


def lock_editable_repair(session: Session, repair_id: int) -> None:
    """Serialize item edits and status changes, including concurrent completion."""
    order = session.execute(
        select(RepairOrder)
        .where(col(RepairOrder.id) == repair_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Repair order not found")
    if order.status in {RepairStatus.COMPLETED, RepairStatus.CANCELLED}:
        raise HTTPException(
            409, "Items cannot be changed on completed or cancelled repairs"
        )


def create_item(
    session: Session, repair_id: int, data: RepairItemCreate
) -> RepairItemRead:
    """Persist a line and a content-free audit fact in one transaction."""
    lock_editable_repair(session, repair_id)
    item = RepairItem(repair_order_id=repair_id, **data.model_dump())
    session.add(item)
    session.flush()
    record_event(
        session,
        AuditAction.REPAIR_ITEM_CREATED,
        AuditResource.REPAIR_ITEM,
        item.id,
        actor_id=session.info.get("audit_actor_id"),
        details=AuditDetails(repair_order_id=repair_id),
    )
    session.commit()
    session.refresh(item)
    return read_item(item)


def update_item(
    session: Session, repair_id: int, item_id: int, data: RepairItemUpdate
) -> RepairItemRead:
    """Update only supplied fields; an item from another repair is not a match."""
    lock_editable_repair(session, repair_id)
    item = session.execute(
        select(RepairItem).where(
            col(RepairItem.id) == item_id, col(RepairItem.repair_order_id) == repair_id
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Repair item not found")
    changes = {
        name: value
        for name, value in data.model_dump(exclude_unset=True).items()
        if getattr(item, name) != value
    }
    if changes:
        item.sqlmodel_update(changes)
        session.add(item)
        record_event(
            session,
            AuditAction.REPAIR_ITEM_UPDATED,
            AuditResource.REPAIR_ITEM,
            item.id,
            actor_id=session.info.get("audit_actor_id"),
            details=AuditDetails(repair_order_id=repair_id),
        )
        session.commit()
        session.refresh(item)
    return read_item(item)
