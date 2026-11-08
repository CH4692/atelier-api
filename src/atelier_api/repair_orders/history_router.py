"""Expose a repair-scoped view without relaxing administrator-only audit access."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response
from sqlalchemy import func
from sqlmodel import col, select

from atelier_api.audit.models import AuditAction, AuditEvent, AuditResource
from atelier_api.audit.schemas import AuditDetails, AuditEventRead
from atelier_api.audit.service import record_event
from atelier_api.auth.dependencies import CurrentUser
from atelier_api.database import SessionDep
from atelier_api.estimates.models import RepairEstimate
from atelier_api.users.roles import UserRole

from .item_models import RepairItem
from .models import RepairDocument, RepairOrder

router = APIRouter(
    tags=["repairs"],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Administrator required for audit history"},
        404: {"description": "Repair order not found"},
        503: {"description": "Database unavailable"},
    },
)

HISTORY_ACTIONS = (
    AuditAction.REPAIR_ORDER_CREATED,
    AuditAction.REPAIR_ORDER_UPDATED,
    AuditAction.REPAIR_STATUS_CHANGED,
    AuditAction.REPAIR_ORDER_ARCHIVED,
    AuditAction.REPAIR_ORDER_RESTORED,
    AuditAction.REPAIR_ITEM_CREATED,
    AuditAction.REPAIR_ITEM_UPDATED,
    AuditAction.REPAIR_DOCUMENT_CREATED,
    AuditAction.ESTIMATE_CREATED,
    AuditAction.ESTIMATE_UPDATED,
    AuditAction.ESTIMATE_STATUS_CHANGED,
    AuditAction.ESTIMATE_APPROVED,
)


@router.get(
    "/repairs/{repair_id}/history",
    response_model=list[AuditEventRead],
    summary="Read retained repair audit history as administrator",
    responses={
        200: {
            "headers": {
                "X-Total-Count": {
                    "description": "Retained matching events before pagination",
                    "schema": {"type": "integer", "minimum": 0},
                }
            }
        }
    },
)
def get_repair_history(
    repair_id: Annotated[int, Path(gt=0)],
    user: CurrentUser,
    session: SessionDep,
    response: Response,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AuditEventRead]:
    """Order by UTC occurrence time and ID; include archived repairs.

    Related-resource joins include older events without parent metadata. Stored
    parent identifiers retain the association if a child is later purged through
    a controlled retention procedure. Audit retention still applies; unknown
    historical actors or missing expired events are never reconstructed.
    """
    if user.role != UserRole.ADMIN:
        record_event(
            session,
            AuditAction.AUDIT_DENIED,
            AuditResource.AUDIT,
            actor_id=user.id,
            details=AuditDetails(repair_order_id=repair_id),
        )
        session.commit()
        raise HTTPException(403, "Administrator required for audit history")
    if session.get(RepairOrder, repair_id) is None:
        raise HTTPException(404, "Repair order not found")
    parent = col(AuditEvent.details)["repair_order_id"].as_string() == str(repair_id)
    scope = (col(AuditEvent.resource_type) == AuditResource.REPAIR_ORDER) & (
        col(AuditEvent.resource_id) == repair_id
    )
    for resource, table, foreign_key in (
        (AuditResource.REPAIR_ITEM, RepairItem, col(RepairItem.repair_order_id)),
        (
            AuditResource.REPAIR_DOCUMENT,
            RepairDocument,
            col(RepairDocument.repair_order_id),
        ),
        (
            AuditResource.REPAIR_ESTIMATE,
            RepairEstimate,
            col(RepairEstimate.repair_order_id),
        ),
    ):
        scope = scope | (
            (col(AuditEvent.resource_type) == resource)
            & (
                parent
                | col(AuditEvent.resource_id).in_(
                    select(table.id).where(foreign_key == repair_id)
                )
            )
        )
    statement = select(AuditEvent).where(
        scope, col(AuditEvent.action).in_(HISTORY_ACTIONS)
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Total-Count"] = str(
        session.exec(select(func.count()).select_from(statement.subquery())).one()
    )
    events = session.exec(
        statement.order_by(col(AuditEvent.occurred_at), col(AuditEvent.id))
        .offset(offset)
        .limit(limit)
    ).all()
    result = [AuditEventRead.model_validate(event) for event in events]
    record_event(
        session,
        AuditAction.AUDIT_READ,
        AuditResource.AUDIT,
        actor_id=user.id,
        details=AuditDetails(repair_order_id=repair_id),
    )
    session.commit()
    return result
