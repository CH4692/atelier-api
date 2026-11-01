"""Define the validated repair-order states shared by API and database models."""

from enum import StrEnum


class RepairStatus(StrEnum):
    """Classify accepted orders and preserved historical work."""

    ACCEPTED = "accepted"
    AWAITING_APPROVAL = "awaiting_approval"
    IN_PROGRESS = "in_progress"
    AWAITING_MATERIALS = "awaiting_materials"
    READY_FOR_PICKUP = "ready_for_pickup"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
