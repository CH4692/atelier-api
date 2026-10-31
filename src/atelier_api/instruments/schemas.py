"""Validate instrument details for persistence and API representations."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    FiniteFloat,
    Strict,
    field_validator,
    model_validator,
)
from sqlalchemy import Enum, Text
from sqlmodel import Field, SQLModel

Measurement = Annotated[FiniteFloat, Strict()]


class InstrumentType(StrEnum):
    """Classify string instruments and bows using one canonical category field."""

    VIOLIN = "violin"
    VIOLA = "viola"
    CELLO = "cello"
    DOUBLE_BASS = "double_bass"
    BOW = "bow"


def validate_category_attributes(
    instrument_type: InstrumentType,
    body_length_mm: float | None,
    bow_weight_g: float | None,
) -> None:
    """Reject irrelevant attributes without silently discarding stored values."""
    if instrument_type == InstrumentType.BOW:
        if body_length_mm is not None:
            raise ValueError("Bows cannot have body_length_mm; clear it explicitly")
    elif bow_weight_g is not None:
        raise ValueError("Only bows can have bow_weight_g; clear it explicitly")


class InstrumentOwnership(StrEnum):
    """Distinguish known workshop stock from customer or unassigned ownership."""

    CUSTOMER = "customer"
    WORKSHOP = "workshop"
    UNASSIGNED = "unassigned"


class InstrumentSortField(StrEnum):
    """Allow only explicit public fields as SQL sorting targets."""

    ID = "id"
    IDENTIFICATION_NUMBER = "identification_number"
    TYPE = "type"
    MAKER = "maker"
    YEAR_OF_MANUFACTURE = "year_of_manufacture"
    CUSTOMER_ID = "customer_id"
    OWNERSHIP = "ownership"


class InstrumentSortOrder(StrEnum):
    """Define the supported sort directions."""

    ASC = "asc"
    DESC = "desc"


class InstrumentBase(SQLModel):
    """Share instrument fields across the table and input/output schemas.

    Only type is required. Legacy customer assignments infer customer ownership;
    otherwise ownership defaults to unassigned. Workshop stock is explicit.
    Customer ownership can retain an unknown owner after customer deletion.
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
        ),
        index=True,
    )
    body_length_mm: Measurement | None = Field(default=None, gt=0)
    bow_weight_g: Measurement | None = Field(default=None, gt=0)
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
    ownership: InstrumentOwnership = Field(
        default=InstrumentOwnership.UNASSIGNED,
        sa_type=Enum(
            InstrumentOwnership,
            values_callable=lambda entries: [entry.value for entry in entries],
            native_enum=False,
            create_constraint=True,
            name="ck_instrument_ownership",
            length=16,
        ),
        index=True,
    )

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_ownership(cls, value: object) -> object:
        """Preserve older create requests that supplied only customer_id."""
        if isinstance(value, dict) and "ownership" not in value:
            return {
                **value,
                "ownership": InstrumentOwnership.CUSTOMER
                if value.get("customer_id") is not None
                else InstrumentOwnership.UNASSIGNED,
            }
        return value

    @model_validator(mode="after")
    def validate_owner(self) -> InstrumentBase:
        if (
            self.customer_id is not None
            and self.ownership != InstrumentOwnership.CUSTOMER
        ):
            raise ValueError("Only customer-owned instruments can reference a customer")
        validate_category_attributes(self.type, self.body_length_mm, self.bow_weight_g)
        return self


class InstrumentCreate(InstrumentBase):
    """Accept instrument details without a client-supplied identifier."""


class InstrumentRead(InstrumentBase):
    """Represent a stored instrument with its database-generated identifier."""

    id: int


class InstrumentUpdate(SQLModel):
    """Validate supplied changes while preserving omitted instrument fields.

    Optional details and the customer association can be cleared with null.
    Type and ownership cannot explicitly be null. Ownership/customer combinations
    are validated against the locked current record by the update service.
    """

    model_config = {"extra": "forbid"}

    type: InstrumentType | None = None
    body_length_mm: Measurement | None = Field(default=None, gt=0)
    bow_weight_g: Measurement | None = Field(default=None, gt=0)
    maker: str | None = None
    year_of_manufacture: int | None = Field(default=None, ge=1, le=9999)
    identification_number: str | None = None
    notes: str | None = None
    customer_id: int | None = Field(default=None, gt=0)
    ownership: InstrumentOwnership | None = None

    @field_validator("ownership")
    @classmethod
    def reject_null_ownership(
        cls, value: InstrumentOwnership | None
    ) -> InstrumentOwnership:
        if value is None:
            raise ValueError("Ownership cannot be null")
        return value

    @field_validator("type")
    @classmethod
    def reject_null_type(cls, value: InstrumentType | None) -> InstrumentType:
        """Reject clearing the required type while allowing it to be omitted.

        Args:
            value: The instrument type supplied in the update.

        Returns:
            The supplied non-null instrument type.

        Raises:
            ValueError: If the supplied type is null.
        """
        if value is None:
            raise ValueError("Instrument type cannot be null")
        return value


class InstrumentOwnershipRead(SQLModel):
    """Expose minimal ownership facts without copying customer personal data."""

    id: int
    instrument_id: int
    previous_ownership: InstrumentOwnership | None
    previous_customer_id: int | None
    ownership: InstrumentOwnership
    customer_id: int | None
    actor_id: int | None
    source: str
    recorded_at: AwareDatetime

    @field_validator("recorded_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)
