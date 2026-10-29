"""Append explicit events in the caller's transaction without logging payloads."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, insert
from sqlmodel import Session, col

from .models import AuditAction, AuditEvent, AuditResource
from .schemas import AuditDetails


def record_event(
    session: Session,
    action: AuditAction,
    resource_type: AuditResource,
    resource_id: int | None = None,
    *,
    actor_id: int | None = None,
    succeeded: bool = True,
    details: AuditDetails | None = None,
) -> None:
    """Append an event without committing or accepting arbitrary request data.

    Callers pass only actors established by a validated session or trusted local
    administrative adapter. Failed login
    attempts deliberately omit email, IP address and any guessed account ID.
    """
    session.execute(
        insert(AuditEvent).values(
            action=action.value,
            resource_type=resource_type.value,
            resource_id=resource_id,
            actor_id=actor_id,
            occurred_at=datetime.now(UTC),
            succeeded=succeeded,
            details=details.model_dump(mode="json", exclude_unset=True)
            if details
            else {},
        )
    )


def purge_expired_events(session: Session, retention_days: int) -> int:
    """Delete expired records through the trusted operator retention command."""
    if retention_days < 1:
        raise ValueError("Audit retention must be at least one day")
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    ids = session.execute(
        delete(AuditEvent)
        .where(col(AuditEvent.occurred_at) < cutoff)
        .returning(col(AuditEvent.id))
    ).all()
    record_event(
        session,
        AuditAction.RETENTION,
        AuditResource.AUDIT,
        details=AuditDetails(removed_count=len(ids)),
    )
    session.commit()
    return len(ids)
