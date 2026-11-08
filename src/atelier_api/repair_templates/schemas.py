"""Validate template text and exact optional monetary defaults."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from atelier_api.repair_orders.item_schemas import Description, UnitPrice

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class RepairTemplateCreate(BaseModel):
    """Require meaningful text; a missing price does not imply a free service."""

    model_config = ConfigDict(extra="forbid")
    name: Name
    description: Description
    default_unit_price: UnitPrice | None = None


class RepairTemplateUpdate(BaseModel):
    """Preserve omitted values and allow clearing the optional default price."""

    model_config = ConfigDict(extra="forbid")
    name: Name | None = None
    description: Description | None = None
    default_unit_price: UnitPrice | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Template text cannot be null")
        return value


class RepairTemplateRead(RepairTemplateCreate):
    """Expose selectable template values, without any customer information."""

    model_config = ConfigDict(from_attributes=True)
    id: int
