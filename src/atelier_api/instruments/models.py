"""Persist instruments without deleting them when their customer is removed."""

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import CheckConstraint, DateTime, Index, func
from sqlmodel import Field, Relationship, SQLModel

from atelier_api.customers.models import Customer

from .schemas import InstrumentBase, InstrumentOwnership


class Instrument(InstrumentBase, table=True):
    """Store instrument details with an optional customer relationship.

    Database constraints protect type and year even for direct SQL writes.
    Customer deletion clears the foreign key and preserves the instrument.
    Identification numbers are not assumed to be globally unique.
    """

    __table_args__ = (
        CheckConstraint(
            "body_length_mm > 0 AND body_length_mm < 'Infinity'::double precision",
            name="ck_instrument_body_length",
        ),
        CheckConstraint(
            "bow_weight_g > 0 AND bow_weight_g < 'Infinity'::double precision",
            name="ck_instrument_bow_weight",
        ),
        CheckConstraint(
            "(type = 'bow' AND body_length_mm IS NULL) OR (type <> 'bow' AND bow_weight_g IS NULL)",
            name="ck_instrument_category_attributes",
        ),
        CheckConstraint(
            "customer_id IS NULL OR ownership = 'customer'",
            name="ck_instrument_owner_category",
        ),
        CheckConstraint(
            "year_of_manufacture BETWEEN 1 AND 9999",
            name="ck_instrument_year_of_manufacture",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    customer: Customer | None = Relationship()

    def __init__(self, **data: object) -> None:
        """Preserve inference for trusted ORM construction, which skips validators."""
        if "ownership" not in data:
            data["ownership"] = (
                InstrumentOwnership.CUSTOMER
                if data.get("customer_id") is not None
                else InstrumentOwnership.UNASSIGNED
            )
        SQLModel.__init__(self, **data)


class InstrumentOwnershipEvent(SQLModel, table=True):
    """Retain minimal historical references independently of account/resource deletion.

    A PostgreSQL trigger appends events atomically, including FK disassociations.
    No cascading foreign keys may erase the former owner or instrument reference.
    """

    __tablename__: ClassVar[str] = "instrument_ownership_event"
    __table_args__ = (
        Index("ix_instrument_ownership_event_instrument_id_id", "instrument_id", "id"),
    )
    id: int | None = Field(default=None, primary_key=True)
    instrument_id: int
    previous_ownership: str | None = Field(default=None, max_length=16)
    previous_customer_id: int | None = None
    ownership: str = Field(max_length=16)
    customer_id: int | None = None
    actor_id: int | None = None
    source: str = Field(max_length=16)
    recorded_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
