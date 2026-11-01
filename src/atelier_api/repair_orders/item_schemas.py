"""Validate bounded quantities, prices and partial changes to repair positions."""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .item_models import RepairItemKind

Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
Quantity = Annotated[
    Decimal,
    Field(
        gt=0,
        le=Decimal("999999.999"),
        max_digits=9,
        decimal_places=3,
        allow_inf_nan=False,
    ),
]
UnitPrice = Annotated[
    Decimal,
    Field(
        ge=0,
        le=Decimal("9999999999.99"),
        max_digits=12,
        decimal_places=2,
        allow_inf_nan=False,
    ),
]


class RepairItemCreate(BaseModel):
    """Accept a service or material line; monetary JSON strings preserve precision."""

    model_config = ConfigDict(extra="forbid")
    kind: RepairItemKind
    description: Description
    quantity: Quantity
    unit_price: UnitPrice


class RepairItemUpdate(BaseModel):
    """Preserve omitted fields and reject explicit null for every item field."""

    model_config = ConfigDict(extra="forbid")
    kind: RepairItemKind | None = None
    description: Description | None = None
    quantity: Quantity | None = None
    unit_price: UnitPrice | None = None

    @field_validator("kind", "description", "quantity", "unit_price", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Repair item fields cannot be null")
        return value


class RepairItemRead(RepairItemCreate):
    """Return an exact line amount derived from the stored quantity and price."""

    id: int
    repair_order_id: int
    line_total: Decimal


class RepairItemsRead(BaseModel):
    """Return ordered positions and totals from the same database snapshot."""

    repair_order_id: int
    items: list[RepairItemRead]
    service_total: Decimal
    material_total: Decimal
    total: Decimal
