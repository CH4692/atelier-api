"""Validate instrument details for persistence and API representations."""

from enum import StrEnum

from sqlalchemy import Enum, Text
from sqlmodel import Field, SQLModel


class InstrumentType(StrEnum):
    """List the instrument types supported by the initial data model."""

    VIOLIN = "violin"
    VIOLA = "viola"
    CELLO = "cello"
    DOUBLE_BASS = "double_bass"


class InstrumentBase(SQLModel):
    """Share instrument fields across the table and input/output schemas.

    Only type is required. An omitted customer represents an unassigned
    instrument, including workshop stock. Unknown manufacture years stay null.
    """

    model_config = {"extra": "forbid"}

    type: InstrumentType = Field(
        sa_type=Enum(
            InstrumentType,
            values_callable=lambda entries: [entry.value for entry in entries],
            native_enum=False,
            create_constraint=True,
            name="ck_instrument_type",
            length=32,
        )
    )
    maker: str | None = None
    year_of_manufacture: int | None = Field(default=None, ge=1, le=9999)
    identification_number: str | None = None
    notes: str | None = Field(default=None, sa_type=Text)
    customer_id: int | None = Field(
        default=None,
        gt=0,
        foreign_key="customer.id",
        ondelete="SET NULL",
        index=True,
    )


class InstrumentCreate(InstrumentBase):
    """Accept instrument details without a client-supplied identifier."""


class InstrumentRead(InstrumentBase):
    """Represent a stored instrument with its database-generated identifier."""

    id: int
