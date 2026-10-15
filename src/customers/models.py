from pydantic import BaseModel, EmailStr

class BaseCustomer(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr
    phone: str | None = None




