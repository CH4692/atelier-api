from sqlmodel import Field

from .schemas import CustomerBase


class Customer(CustomerBase, table=True):
    id: int | None = Field(default=None, primary_key=True) 
