"""Provide a bounded, administrator-only view of historical audit facts."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, select

from atelier_api.auth.dependencies import CurrentUser
from atelier_api.database import SessionDep
from atelier_api.users.roles import UserRole

from .models import AuditAction, AuditEvent, AuditResource
from .schemas import AuditEventRead
from .service import record_event

router = APIRouter(prefix="/audit-events", tags=["audit"])


@router.get(
    "",
    summary="List audit events as administrator",
    response_model=list[AuditEventRead],
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Administrator required"},
    },
)
def list_audit_events(
    user: CurrentUser,
    session: SessionDep,
    actor_id: int | None = None,
    action: AuditAction | None = None,
    resource_type: AuditResource | None = None,
    resource_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AuditEventRead]:
    """Filter events using inclusive timezone-aware dates and descending ID pagination."""
    if user.role != UserRole.ADMIN:
        record_event(
            session,
            AuditAction.AUDIT_DENIED,
            AuditResource.AUDIT,
            actor_id=user.id,
            succeeded=False,
        )
        session.commit()
        raise HTTPException(403, "Administrator required")
    for date in (since, until):
        if date is not None and date.utcoffset() is None:
            raise HTTPException(422, "Audit dates must include a timezone")
    if since is not None and until is not None and since > until:
        raise HTTPException(422, "Invalid audit date range")
    statement = select(AuditEvent)
    for column, value in (
        (col(AuditEvent.actor_id), actor_id),
        (col(AuditEvent.resource_id), resource_id),
        (col(AuditEvent.action), action),
        (col(AuditEvent.resource_type), resource_type),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if since is not None:
        statement = statement.where(
            col(AuditEvent.occurred_at) >= since.astimezone(UTC)
        )
    if until is not None:
        statement = statement.where(
            col(AuditEvent.occurred_at) <= until.astimezone(UTC)
        )
    if before_id is not None:
        statement = statement.where(col(AuditEvent.id) < before_id)
    events = session.exec(
        statement.order_by(col(AuditEvent.id).desc()).limit(limit)
    ).all()
    result = [AuditEventRead.model_validate(event) for event in events]
    record_event(
        session,
        AuditAction.AUDIT_READ,
        AuditResource.AUDIT,
        actor_id=user.id,
    )
    session.commit()
    return result
