from pydantic import BaseModel, EmailStr

class BaseCustomer(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None = None

class CustomerRead(BaseCustomer):
    id: int



