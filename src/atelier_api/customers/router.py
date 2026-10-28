"""Expose customer creation, retrieval, partial updates and deletion over HTTP."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import select

from atelier_api.database import SessionDep

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
async def get_customers(session: SessionDep) -> list[CustomerRead]:
    """Return all customers without pagination or an explicit sort order."""
    customers = session.exec(select(Customer)).all()
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
    session.delete(customer)
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
        session.commit()
        session.refresh(customer)
    return CustomerRead.model_validate(customer)
