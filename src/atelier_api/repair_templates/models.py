"""Persist reusable values independently of repair snapshots."""

from decimal import Decimal
from typing import ClassVar

from sqlalchemy import CheckConstraint, Numeric, Text
from sqlmodel import Field, SQLModel


class RepairTemplate(SQLModel, table=True):
    """Store defaults without propagating edits into existing repairs."""

    __tablename__: ClassVar[str] = "repair_template"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 100", name="ck_repair_template_name"
        ),
        CheckConstraint(
            "length(btrim(description)) BETWEEN 1 AND 2000",
            name="ck_repair_template_description",
        ),
        CheckConstraint(
            "default_unit_price >= 0 AND default_unit_price <= 9999999999.99",
            name="ck_repair_template_price",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    description: str = Field(sa_type=Text)
    default_unit_price: Decimal | None = Field(default=None, sa_type=Numeric(12, 2))
