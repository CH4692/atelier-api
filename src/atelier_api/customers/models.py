"""Define the persisted customer table."""

from sqlmodel import Field

from .schemas import CustomerBase


class Customer(CustomerBase, table=True):
    """Store customer details with a database-generated primary key."""

    id: int | None = Field(default=None, primary_key=True)
