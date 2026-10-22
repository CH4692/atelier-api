from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from atelier_api.database import SessionDep

from .models import Customer
from .schemas import CustomerCreate, CustomerRead

customers_router = APIRouter(prefix="/customers")

@customers_router.get("", tags=["customers"])
async def get_customers(session: SessionDep) -> list[CustomerRead]:
    customers = session.exec(select(Customer)).all()
    return [
                CustomerRead.model_validate(customer)
                for customer in customers
            ]

@customers_router.post("", tags=["customers"], status_code=status.HTTP_201_CREATED,)
async def create_customer(customer: CustomerCreate, session:SessionDep) -> CustomerRead:
    db_customer = Customer.model_validate(customer)
    session.add(db_customer)
    session.commit()
    session.refresh(db_customer)
    return CustomerRead.model_validate(db_customer)

@customers_router.get("/{customer_id}", tags=["customers"])
async def get_customer_by_id(customer_id: int, session:SessionDep) -> CustomerRead:
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    return CustomerRead.model_validate(customer)
