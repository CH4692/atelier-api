"""Persist repair services and materials using exact PostgreSQL numeric types."""

from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from sqlalchemy import CheckConstraint, Enum, Numeric, Text
from sqlmodel import Field, SQLModel


class RepairItemKind(StrEnum):
    """Distinguish workshop services from material costs."""

    SERVICE = "service"
    MATERIAL = "material"


class RepairItem(SQLModel, table=True):
    """Keep many cost positions attached to one repair without cascading deletion."""

    __tablename__: ClassVar[str] = "repair_item"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(description)) BETWEEN 1 AND 2000",
            name="ck_repair_item_description",
        ),
        CheckConstraint(
            "quantity > 0 AND quantity <= 999999.999", name="ck_repair_item_quantity"
        ),
        CheckConstraint(
            "unit_price >= 0 AND unit_price <= 9999999999.99",
            name="ck_repair_item_unit_price",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    repair_order_id: int = Field(
        foreign_key="repair_order.id", ondelete="RESTRICT", index=True
    )
    kind: RepairItemKind = Field(
        sa_type=Enum(
            RepairItemKind,
            values_callable=lambda values: [value.value for value in values],
            native_enum=False,
            create_constraint=True,
            name="ck_repair_item_kind",
            length=16,
        )
    )
    description: str = Field(sa_type=Text)
    quantity: Decimal = Field(sa_type=Numeric(9, 3))
    unit_price: Decimal = Field(sa_type=Numeric(12, 2))
