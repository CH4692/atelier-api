"""Expose the current instruments associated with a customer."""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from atelier_api.customers.models import Customer
from atelier_api.database import SessionDep

from .models import Instrument
from .schemas import InstrumentRead

customer_instruments_router = APIRouter(prefix="/customers", tags=["customers"])


@customer_instruments_router.get(
    "/{customer_id}/instruments",
    summary="List a customer's instruments",
    response_model=list[InstrumentRead],
    responses={
        404: {"description": "Customer not found"},
        503: {"description": "Database unavailable"},
    },
)
def get_customer_instruments(
    customer_id: int, session: SessionDep
) -> list[InstrumentRead]:
    """Return only instruments currently associated with the customer.

    An existing customer without instruments returns an empty list. This is
    the current association, not a historical ownership record. Unassigned
    instruments are excluded. Results have no explicit ordering or pagination.

    Raises:
        HTTPException: With status 404 if the customer does not exist.
    """
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    instruments = session.exec(
        select(Instrument).where(Instrument.customer_id == customer_id)
    ).all()
    return [InstrumentRead.model_validate(instrument) for instrument in instruments]
