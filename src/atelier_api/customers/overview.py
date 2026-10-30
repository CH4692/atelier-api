"""Compose customer details with their related workshop resources."""

from pydantic import BaseModel

from atelier_api.instruments.schemas import InstrumentRead

from .schemas import CustomerRead


class CustomerOverview(BaseModel):
    """Return customer details and the instruments currently assigned to them."""

    customer: CustomerRead
    instruments: list[InstrumentRead]
