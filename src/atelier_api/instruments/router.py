"""Register, retrieve, update and delete instruments."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import select

from atelier_api.customers.models import Customer
from atelier_api.database import SessionDep

from .models import Instrument
from .schemas import InstrumentCreate, InstrumentRead, InstrumentUpdate

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


@instruments_router.get(
    "/{instrument_id}",
    summary="Get an instrument by ID",
    response_model=InstrumentRead,
    responses={
        404: {"description": "Instrument not found"},
        503: {"description": "Database unavailable"},
    },
)
def get_instrument_by_id(instrument_id: int, session: SessionDep) -> InstrumentRead:
    """Return the instrument details and its optional associated customer ID.

    Unassigned instruments include customer_id as null.

    Raises:
        HTTPException: With status 404 if the instrument does not exist.
    """
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found",
        )
    return InstrumentRead.model_validate(instrument)


@instruments_router.delete(
    "/{instrument_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an instrument",
    responses={
        404: {"description": "Instrument not found"},
        503: {"description": "Database unavailable"},
    },
)
def delete_instrument(instrument_id: int, session: SessionDep) -> Response:
    """Permanently delete an instrument while preserving its customer.

    Deletion is committed before returning an empty response. Repeating the
    request for the deleted identifier returns 404.

    Args:
        instrument_id: The identifier of the instrument to delete.
        session: The database session provided for this request.

    Returns:
        HTTP 204 without a response body after successful deletion.

    Raises:
        HTTPException: With status 404 if the instrument does not exist.
    """
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found",
        )
    session.delete(instrument)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@instruments_router.patch(
    "/{instrument_id}",
    summary="Update instrument information",
    response_model=InstrumentRead,
    responses={
        404: {"description": "Instrument or referenced customer not found"},
        503: {"description": "Database unavailable"},
    },
)
def update_instrument(
    instrument_id: int, instrument_update: InstrumentUpdate, session: SessionDep
) -> InstrumentRead:
    """Update supplied instrument fields and return the complete stored record.

    Omitted fields remain unchanged. Set customer_id to null to remove the
    association, or supply an existing customer's ID to change it. Optional
    details can be cleared with null; type cannot. An empty object is a no-op.

    Args:
        instrument_id: The identifier of the instrument to update.
        instrument_update: Validated changes supplied in the JSON request body.
        session: The database session provided for this request.

    Returns:
        The complete instrument after committing any supplied changes.

    Raises:
        HTTPException: With status 404 if the instrument or customer is missing.
    """
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Instrument not found",
        )
    changes = instrument_update.model_dump(exclude_unset=True)
    if "customer_id" in changes and instrument_update.customer_id is not None:
        customer = session.get(Customer, instrument_update.customer_id)
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
    if changes:
        instrument.sqlmodel_update(changes)
        session.add(instrument)
        session.commit()
        session.refresh(instrument)
    return InstrumentRead.model_validate(instrument)
