"""Register, retrieve, update and delete instruments."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlmodel import col, select

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.service import record_event
from atelier_api.customers.models import Customer
from atelier_api.database import SessionDep

from .models import Instrument, InstrumentOwnershipEvent
from .ownership import ownership_changes, set_ownership_actor
from .schemas import (
    InstrumentCreate,
    InstrumentOwnership,
    InstrumentOwnershipRead,
    InstrumentRead,
    InstrumentSortField,
    InstrumentSortOrder,
    InstrumentType,
    InstrumentUpdate,
    validate_category_attributes,
)

instruments_router = APIRouter(prefix="/instruments", tags=["instruments"])


@instruments_router.get(
    "",
    summary="List registered instruments",
    response_model=list[InstrumentRead],
    responses={
        200: {
            "headers": {
                "X-Total-Count": {
                    "description": "Number of matching instruments before pagination",
                    "schema": {"type": "integer", "minimum": 0},
                }
            }
        },
        503: {"description": "Database unavailable"},
    },
)
def get_instruments(
    session: SessionDep,
    response: Response,
    ownership: InstrumentOwnership | None = None,
    type: InstrumentType | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    customer_id: Annotated[int | None, Query(gt=0)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    sort_by: InstrumentSortField = InstrumentSortField.ID,
    sort_order: InstrumentSortOrder = InstrumentSortOrder.ASC,
) -> list[InstrumentRead]:
    """Search identification numbers and combine filters before pagination.

    Search uses case-insensitive literal substrings; blank search lists all
    matching instruments. Filters are combined with AND. Sorting puts nulls
    last and uses ascending ID to resolve ties. Default order is ascending ID.
    X-Total-Count includes matches beyond the page, even for empty pages.
    Count and page queries may observe concurrent committed changes.
    """
    statement = select(Instrument)
    if ownership is not None:
        statement = statement.where(Instrument.ownership == ownership)
    if type is not None:
        statement = statement.where(Instrument.type == type)
    if customer_id is not None:
        statement = statement.where(Instrument.customer_id == customer_id)
    if q is not None and (term := q.strip()):
        statement = statement.where(
            col(Instrument.identification_number).icontains(term, autoescape=True)
        )
    total = session.exec(select(func.count()).select_from(statement.subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    # Attribute names come exclusively from the validated enum, never raw SQL.
    column = col(getattr(Instrument, sort_by.value))
    ordering = column.desc() if sort_order == InstrumentSortOrder.DESC else column.asc()
    statement = statement.order_by(ordering.nulls_last())
    if sort_by != InstrumentSortField.ID:
        statement = statement.order_by(col(Instrument.id).asc())
    instruments = session.exec(statement.offset(offset).limit(limit)).all()
    return [InstrumentRead.model_validate(instrument) for instrument in instruments]


@instruments_router.get(
    "/{instrument_id}/ownership-history",
    summary="List an instrument's ownership history",
    response_model=list[InstrumentOwnershipRead],
    responses={404: {"description": "Instrument and ownership history not found"}},
)
def get_ownership_history(
    instrument_id: int,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[InstrumentOwnershipRead]:
    """Return newest facts first, including retained history of deleted instruments.

    A migration entry is a snapshot at migration time, not a claimed purchase
    date. Historical customer IDs may refer to subsequently deleted customers.
    """
    statement = select(InstrumentOwnershipEvent).where(
        InstrumentOwnershipEvent.instrument_id == instrument_id
    )
    if (
        session.get(Instrument, instrument_id) is None
        and session.exec(statement.limit(1)).first() is None
    ):
        raise HTTPException(404, "Instrument not found")
    events = session.exec(
        statement.order_by(col(InstrumentOwnershipEvent.id).desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [InstrumentOwnershipRead.model_validate(event) for event in events]


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
    record_event(
        session,
        AuditAction.INSTRUMENT_DELETED,
        AuditResource.INSTRUMENT,
        instrument.id,
        actor_id=session.info.get("audit_actor_id"),
    )
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
    set_ownership_actor(session)
    session.add(db_instrument)
    session.flush()
    record_event(
        session,
        AuditAction.INSTRUMENT_CREATED,
        AuditResource.INSTRUMENT,
        db_instrument.id,
        actor_id=session.info.get("audit_actor_id"),
    )
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
    session.refresh(instrument, with_for_update=True)
    try:
        changes = ownership_changes(instrument, instrument_update)
        validate_category_attributes(
            changes.get("type", instrument.type),
            changes.get("body_length_mm", instrument.body_length_mm),
            changes.get("bow_weight_g", instrument.bow_weight_g),
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if "customer_id" in changes and instrument_update.customer_id is not None:
        customer = session.get(Customer, instrument_update.customer_id)
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
    if changes:
        set_ownership_actor(session)
        instrument.sqlmodel_update(changes)
        session.add(instrument)
        record_event(
            session,
            AuditAction.INSTRUMENT_UPDATED,
            AuditResource.INSTRUMENT,
            instrument.id,
            actor_id=session.info.get("audit_actor_id"),
        )
        session.commit()
        session.refresh(instrument)
    return InstrumentRead.model_validate(instrument)
