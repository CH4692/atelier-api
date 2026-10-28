"""Persist instruments without deleting them when their customer is removed."""

from sqlalchemy import CheckConstraint
from sqlmodel import Field, Relationship

from atelier_api.customers.models import Customer

from .schemas import InstrumentBase


class Instrument(InstrumentBase, table=True):
    """Store instrument details with an optional customer relationship.

    Database constraints protect type and year even for direct SQL writes.
    Customer deletion clears the foreign key and preserves the instrument.
    Identification numbers are not assumed to be globally unique.
    """

    __table_args__ = (
        CheckConstraint(
            "year_of_manufacture BETWEEN 1 AND 9999",
            name="ck_instrument_year_of_manufacture",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    customer: Customer | None = Relationship()
