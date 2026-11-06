"""Serialize estimate workflow and approval while preserving historical snapshots."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlmodel import Session, col

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event
from atelier_api.repair_orders.amounts import line_amount, sum_amounts
from atelier_api.repair_orders.item_models import RepairItemKind
from atelier_api.repair_orders.models import RepairOrder
from atelier_api.repair_orders.statuses import RepairStatus

from .models import EstimateItem, EstimateStatus, RepairEstimate
from .schemas import (
    EstimateApproval,
    EstimateItemRead,
    EstimateRead,
    EstimateSummary,
    EstimateWrite,
)


def require_repair(
    session: Session, repair_id: int, *, lock: bool = False
) -> RepairOrder:
    """Keep the parent-before-document lock order shared by repair finalization."""
    statement = select(RepairOrder).where(col(RepairOrder.id) == repair_id)
    if lock:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    order = session.execute(statement).scalar_one_or_none()
    if order is None:
        raise HTTPException(404, "Repair order not found")
    if lock and order.status in {RepairStatus.COMPLETED, RepairStatus.CANCELLED}:
        raise HTTPException(
            409, "Estimates cannot be changed on completed or cancelled repairs"
        )
    return order


def require_estimate(
    session: Session, repair_id: int, estimate_id: int, *, lock: bool = False
) -> RepairEstimate:
    """Reject cross-repair references and optionally refresh the locked snapshot."""
    statement = select(RepairEstimate).where(
        col(RepairEstimate.id) == estimate_id,
        col(RepairEstimate.repair_order_id) == repair_id,
    )
    if lock:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    result = session.execute(statement).scalar_one_or_none()
    if result is None:
        raise HTTPException(404, "Estimate not found")
    return result


def read_estimate(session: Session, estimate: RepairEstimate) -> EstimateRead:
    """Read header and positions under the same document lock for a stable view."""
    rows = (
        session.execute(
            select(EstimateItem)
            .where(col(EstimateItem.estimate_id) == estimate.id)
            .order_by(col(EstimateItem.id))
        )
        .scalars()
        .all()
    )
    items = [
        EstimateItemRead(
            **item.model_dump(), line_total=line_amount(item.quantity, item.unit_price)
        )
        for item in rows
    ]
    services = sum_amounts(
        item.line_total for item in items if item.kind == RepairItemKind.SERVICE
    )
    materials = sum_amounts(
        item.line_total for item in items if item.kind == RepairItemKind.MATERIAL
    )
    return EstimateRead(
        **EstimateSummary.model_validate(estimate).model_dump(),
        items=items,
        service_total=services,
        material_total=materials,
        total=sum_amounts([services, materials]),
    )


def append_items(session: Session, estimate_id: int, data: EstimateWrite) -> None:
    session.add_all(
        [
            EstimateItem(estimate_id=estimate_id, **item.model_dump())
            for item in data.items
        ]
    )
    session.flush()


def commit_estimate(
    session: Session,
    estimate: RepairEstimate,
    action: AuditAction,
    previous_status: EstimateStatus | None = None,
) -> EstimateRead:
    """Build the response before committing to keep it tied to this locked version."""
    session.flush()
    record_event(
        session,
        action,
        AuditResource.REPAIR_ESTIMATE,
        estimate.id,
        actor_id=session.info.get("audit_actor_id"),
        details=AuditDetails(
            repair_order_id=estimate.repair_order_id,
            estimate_status=estimate.status,
            **(
                {"previous_estimate_status": previous_status}
                if previous_status is not None
                else {}
            ),
        ),
    )
    result = read_estimate(session, estimate)
    session.commit()
    return result


def create_estimate(
    session: Session, repair_id: int, data: EstimateWrite
) -> EstimateRead:
    order = require_repair(session, repair_id, lock=True)
    if order.customer_id is None:
        raise HTTPException(409, "Estimate requires a known contracting customer")
    revision = (
        session.execute(
            select(func.coalesce(func.max(RepairEstimate.revision), 0)).where(
                col(RepairEstimate.repair_order_id) == repair_id
            )
        ).scalar_one()
        + 1
    )
    now = datetime.now(UTC)
    estimate = RepairEstimate(
        repair_order_id=repair_id,
        customer_id=order.customer_id,
        revision=revision,
        created_at=now,
        status_updated_at=now,
        created_by=session.info.get("audit_actor_id"),
    )
    session.add(estimate)
    session.flush()
    assert estimate.id is not None
    append_items(session, estimate.id, data)
    return commit_estimate(session, estimate, AuditAction.ESTIMATE_CREATED)


def edit_estimate(
    session: Session, repair_id: int, estimate_id: int, data: EstimateWrite
) -> EstimateRead:
    require_repair(session, repair_id, lock=True)
    estimate = require_estimate(session, repair_id, estimate_id, lock=True)
    if estimate.status != EstimateStatus.DRAFT:
        raise HTTPException(409, "Only draft estimates can be edited")
    session.execute(
        delete(EstimateItem).where(col(EstimateItem.estimate_id) == estimate_id)
    )
    append_items(session, estimate_id, data)
    return commit_estimate(session, estimate, AuditAction.ESTIMATE_UPDATED)


def transition_estimate(
    session: Session, repair_id: int, estimate_id: int, target: EstimateStatus
) -> EstimateRead:
    require_repair(session, repair_id, lock=True)
    estimate = require_estimate(session, repair_id, estimate_id, lock=True)
    allowed = {
        EstimateStatus.DRAFT: {EstimateStatus.ISSUED, EstimateStatus.WITHDRAWN},
        EstimateStatus.ISSUED: {EstimateStatus.REJECTED, EstimateStatus.WITHDRAWN},
    }
    if estimate.status == target:
        return read_estimate(session, estimate)
    if target not in allowed.get(estimate.status, set()):
        raise HTTPException(409, "Estimate status transition is not permitted")
    previous = estimate.status
    estimate.status = target
    estimate.status_updated_at = max(datetime.now(UTC), estimate.status_updated_at)
    if target == EstimateStatus.ISSUED:
        estimate.issued_at = estimate.status_updated_at
    session.add(estimate)
    return commit_estimate(
        session, estimate, AuditAction.ESTIMATE_STATUS_CHANGED, previous
    )


def approve_estimate(
    session: Session, repair_id: int, estimate_id: int, data: EstimateApproval
) -> EstimateRead:
    require_repair(session, repair_id, lock=True)
    estimate = require_estimate(session, repair_id, estimate_id, lock=True)
    if estimate.status != EstimateStatus.ISSUED:
        raise HTTPException(409, "Only issued estimates can be approved")
    now = datetime.now(UTC)
    assert estimate.issued_at is not None
    if data.approved_at < estimate.issued_at or data.approved_at > now:
        raise HTTPException(422, "Approval must be between issue and recording time")
    estimate.status = EstimateStatus.APPROVED
    estimate.status_updated_at = max(now, estimate.status_updated_at)
    estimate.approved_at = data.approved_at
    estimate.approval_method = data.approval_method
    estimate.approval_reference = data.approval_reference
    estimate.approval_recorded_at = now
    estimate.approval_recorded_by = session.info.get("audit_actor_id")
    session.add(estimate)
    return commit_estimate(
        session, estimate, AuditAction.ESTIMATE_APPROVED, EstimateStatus.ISSUED
    )
