"""Verify timezone guarantees independently of database configuration."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from atelier_api.audit.schemas import AuditEventRead


def test_audit_response_normalizes_aware_timestamp_to_utc():
    timestamp = datetime(2026, 10, 29, 12, tzinfo=timezone(timedelta(hours=2)))
    event = AuditEventRead(
        id=1,
        action="audit.read",
        resource_type="audit",
        resource_id=None,
        actor_id=2,
        occurred_at=timestamp,
        succeeded=True,
        details={},
    )
    assert event.occurred_at == timestamp
    assert event.occurred_at.tzinfo == UTC
    assert event.model_dump(mode="json")["occurred_at"] == "2026-10-29T10:00:00Z"


def test_audit_response_rejects_naive_timestamp():
    with pytest.raises(ValidationError, match="timezone"):
        AuditEventRead(
            id=1,
            action="audit.read",
            resource_type="audit",
            resource_id=None,
            actor_id=None,
            occurred_at=datetime(2026, 10, 29),
            succeeded=True,
            details={},
        )
