from pydantic import EmailStr
from sqlmodel import SQLModel


class CustomerBase(SQLModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None = None

class CustomerRead(CustomerBase):
    id: int

class CustomerCreate(CustomerBase):
    pass



