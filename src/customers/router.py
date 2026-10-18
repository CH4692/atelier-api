from fastapi import APIRouter
from .schemas import CustomerRead

customers_router = APIRouter(prefix="/customers")

customers: list[CustomerRead] = [ 
    CustomerRead(
        id= 1,
        first_name= "Charles",
        last_name= "Heller",
        email= "charles.heller@hotmail.de",
        phone= "+49123456789"
    ),
    CustomerRead(
        id=2,
        first_name= "David",
        last_name= "Amoako",
        email= "example@hotmail.de",
        phone= "+49123456789"
    )
]
@customers_router.get("", tags=["customers"])
async def get_customers() -> list[CustomerRead]:
    return customers