"""Define document states and customer approval channels."""

from enum import StrEnum


class EstimateStatus(StrEnum):
    """Represent document state independently of the repair's workshop status."""

    DRAFT = "draft"
    ISSUED = "issued"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ApprovalMethod(StrEnum):
    """Describe how staff received the customer's approval."""

    IN_PERSON = "in_person"
    PHONE = "phone"
    EMAIL = "email"
    WRITTEN = "written"
