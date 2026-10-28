"""Register and list instruments with their optional customer association."""

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from atelier_api.customers.models import Customer
from atelier_api.database import SessionDep

from .models import Instrument
from .schemas import InstrumentCreate, InstrumentRead

instruments_router = APIRouter(prefix="/instruments", tags=["instruments"])


@instruments_router.get(
    "",
    summary="List registered instruments",
    response_model=list[InstrumentRead],
    responses={503: {"description": "Database unavailable"}},
)
def get_instruments(session: SessionDep) -> list[InstrumentRead]:
    """Return all instruments, including records without a customer.

    An empty database returns an empty list. Results are not paginated and
    have no explicitly defined sort order.
    """
    instruments = session.exec(select(Instrument)).all()
    return [InstrumentRead.model_validate(instrument) for instrument in instruments]


@instruments_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register an instrument",
    response_model=InstrumentRead,
    responses={
        404: {"description": "Referenced customer not found"},
        503: {"description": "Database unavailable"},
    },
)
def create_instrument(
    instrument: InstrumentCreate, session: SessionDep
) -> InstrumentRead:
    """Store an instrument and return its database-generated identifier.

    Omit customer_id or set it to null to register an unassigned instrument.
    A supplied identifier must reference an existing customer. The record is
    committed before its stored values are returned.

    Args:
        instrument: Validated instrument details from the JSON request body.
        session: The database session provided for this request.

    Returns:
        The stored instrument, including its identifier and optional fields.

    Raises:
        HTTPException: With status 404 if the referenced customer does not exist.
    """
    if instrument.customer_id is not None:
        customer = session.get(Customer, instrument.customer_id)
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
    db_instrument = Instrument.model_validate(instrument)
    session.add(db_instrument)
    session.commit()
    session.refresh(db_instrument)
    return InstrumentRead.model_validate(db_instrument)
