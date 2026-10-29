"""Expose customer creation, retrieval, partial updates and deletion over HTTP."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlmodel import col, or_, select

from atelier_api.audit.models import AuditAction, AuditResource
from atelier_api.audit.schemas import AuditDetails
from atelier_api.audit.service import record_event
from atelier_api.database import SessionDep
from atelier_api.instruments.models import Instrument
from atelier_api.users.service import audit_customer_removal

from .models import Customer
from .schemas import CustomerCreate, CustomerRead, CustomerUpdate

customers_router = APIRouter(prefix="/customers")


@customers_router.get(
    "",
    tags=["customers"],
    summary="List customers",
    response_model=list[CustomerRead],
    responses={503: {"description": "Database unavailable"}},
)
async def get_customers(
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[CustomerRead]:
    """Search names, email and phone using case-insensitive literal substrings.

    Omitted or whitespace-only queries list customers. Results are ordered by ID
    before applying offset and limit. SQL wildcard characters are treated as text.
    Full names can be searched in first-name last-name order.
    """
    statement = select(Customer)
    if q is not None and (term := q.strip()):
        statement = statement.where(
            or_(
                *(
                    column.icontains(term, autoescape=True)
                    for column in (
                        col(Customer.first_name),
                        col(Customer.last_name),
                        col(Customer.first_name) + " " + col(Customer.last_name),
                        col(Customer.email),
                        col(Customer.phone),
                    )
                )
            )
        )
    customers = session.exec(
        statement.order_by(col(Customer.id)).offset(offset).limit(limit)
    ).all()
    return [CustomerRead.model_validate(customer) for customer in customers]


@customers_router.post(
    "",
    tags=["customers"],
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer",
    response_model=CustomerRead,
    responses={503: {"description": "Database unavailable"}},
)
async def create_customer(
    customer: CustomerCreate, session: SessionDep
) -> CustomerRead:
    """Persist customer details and return the database-generated identifier.

    The request commits the new record before refreshing its stored values.
    """
    db_customer = Customer.model_validate(customer)
    session.add(db_customer)
    session.flush()
    record_event(
        session,
        AuditAction.CUSTOMER_CREATED,
        AuditResource.CUSTOMER,
        db_customer.id,
        actor_id=session.info.get("audit_actor_id"),
    )
    session.commit()
    session.refresh(db_customer)
    return CustomerRead.model_validate(db_customer)


@customers_router.get(
    "/{customer_id}",
    tags=["customers"],
    summary="Get a customer by ID",
    response_model=CustomerRead,
    responses={
        404: {"description": "Customer not found"},
        503: {"description": "Database unavailable"},
    },
)
async def get_customer_by_id(customer_id: int, session: SessionDep) -> CustomerRead:
    """Return the customer matching the supplied identifier.

    Raises:
        HTTPException: With status 404 if the customer does not exist.
    """
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    return CustomerRead.model_validate(customer)


@customers_router.delete(
    "/{customer_id}",
    tags=["customers"],
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a customer",
    responses={
        404: {"description": "Customer not found"},
        503: {"description": "Database unavailable"},
    },
)
def delete_customer(customer_id: int, session: SessionDep) -> Response:
    """Permanently delete a customer and return an empty response.

    Deletion is committed before responding. Repeating the request for the
    deleted identifier returns 404.

    Args:
        customer_id: The identifier of the customer to delete.
        session: The database session provided for this request.

    Returns:
        HTTP 204 with no response body after successful deletion.

    Raises:
        HTTPException: With status 404 if the customer does not exist.
    """
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    session.refresh(customer, with_for_update=True)
    audit_customer_removal(customer_id, session)
    instruments = session.exec(
        select(Instrument)
        .where(Instrument.customer_id == customer_id)
        .with_for_update()
    ).all()
    for instrument in instruments:
        record_event(
            session,
            AuditAction.INSTRUMENT_UPDATED,
            AuditResource.INSTRUMENT,
            instrument.id,
            actor_id=session.info.get("audit_actor_id"),
            details=AuditDetails(
                previous_customer_id=customer_id, new_customer_id=None
            ),
        )
    session.delete(customer)
    record_event(
        session,
        AuditAction.CUSTOMER_DELETED,
        AuditResource.CUSTOMER,
        customer.id,
        actor_id=session.info.get("audit_actor_id"),
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@customers_router.patch(
    "/{customer_id}",
    tags=["customers"],
    summary="Update customer information",
    response_model=CustomerRead,
    responses={
        404: {"description": "Customer not found"},
        503: {"description": "Database unavailable"},
    },
)
def update_customer(
    customer_id: int, customer_update: CustomerUpdate, session: SessionDep
) -> CustomerRead:
    """Update supplied fields; omitted fields remain unchanged.

    Set phone to null to remove it. Names and email cannot be null.
    An empty object returns the existing customer unchanged.

    Args:
        customer_id: The identifier of the customer to update.
        customer_update: Validated fields supplied in the request body.
        session: The database session provided for this request.

    Returns:
        The complete customer after committing any supplied changes.

    Raises:
        HTTPException: With status 404 if the customer does not exist.
    """
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    changes = customer_update.model_dump(exclude_unset=True)
    if changes:
        customer.sqlmodel_update(changes)
        session.add(customer)
        record_event(
            session,
            AuditAction.CUSTOMER_UPDATED,
            AuditResource.CUSTOMER,
            customer.id,
            actor_id=session.info.get("audit_actor_id"),
        )
        session.commit()
        session.refresh(customer)
    return CustomerRead.model_validate(customer)
