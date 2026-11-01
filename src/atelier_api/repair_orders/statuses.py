"""Define the repair state machine independently of HTTP and persistence."""

from enum import StrEnum


class RepairStatus(StrEnum):
    """Describe the current workshop stage of a repair order."""

    ACCEPTED = "accepted"
    AWAITING_APPROVAL = "awaiting_approval"
    IN_PROGRESS = "in_progress"
    AWAITING_MATERIALS = "awaiting_materials"
    READY_FOR_PICKUP = "ready_for_pickup"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS: dict[RepairStatus, frozenset[RepairStatus]] = {
    RepairStatus.ACCEPTED: frozenset(
        {
            RepairStatus.AWAITING_APPROVAL,
            RepairStatus.IN_PROGRESS,
            RepairStatus.CANCELLED,
        }
    ),
    RepairStatus.AWAITING_APPROVAL: frozenset(
        {RepairStatus.IN_PROGRESS, RepairStatus.CANCELLED}
    ),
    RepairStatus.IN_PROGRESS: frozenset(
        {
            RepairStatus.AWAITING_APPROVAL,
            RepairStatus.AWAITING_MATERIALS,
            RepairStatus.READY_FOR_PICKUP,
            RepairStatus.CANCELLED,
        }
    ),
    RepairStatus.AWAITING_MATERIALS: frozenset(
        {RepairStatus.IN_PROGRESS, RepairStatus.CANCELLED}
    ),
    RepairStatus.READY_FOR_PICKUP: frozenset(
        {RepairStatus.IN_PROGRESS, RepairStatus.COMPLETED, RepairStatus.CANCELLED}
    ),
    RepairStatus.COMPLETED: frozenset(),
    RepairStatus.CANCELLED: frozenset(),
}


def validate_transition(previous: RepairStatus, target: RepairStatus) -> None:
    """Allow idempotent retries; reject unsupported changes and terminal reopening."""
    if previous != target and target not in ALLOWED_TRANSITIONS[previous]:
        raise ValueError(f"Cannot change repair status from {previous} to {target}")
