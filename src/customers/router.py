from fastapi import APIRouter, status
from sqlmodel import select
from .schemas import CustomerRead, CustomerCreate
from atelier_api.database import SessionDep
from .models import Customer

customers_router = APIRouter(prefix="/customers")

@customers_router.get("", tags=["customers"])
async def get_customers(session: SessionDep) -> list[CustomerRead]:
    customers = session.exec(select(Customer)).all()
    return customers

@customers_router.post("", tags=["customers"], status_code=status.HTTP_201_CREATED,)
async def create_customer(customer: CustomerCreate, session:SessionDep) -> CustomerRead:
    db_customer = Customer.model_validate(customer)
    session.add(db_customer)
    session.commit()
    session.refresh(db_customer)
    return db_customer
