"""Define the persisted customer table."""

from sqlalchemy import CheckConstraint
from sqlmodel import Field

from .schemas import CustomerBase

# Match Python's whitespace stripping, including non-breaking Unicode spaces.
NAME_WHITESPACE_SQL = r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"


class Customer(CustomerBase, table=True):
    """Store customer details with a database-generated primary key."""

    __table_args__ = (
        *(
            CheckConstraint(
                f"{name} <> '' AND {name} = btrim({name}, {NAME_WHITESPACE_SQL})",
                name=f"ck_customer_{name}_normalized",
            )
            for name in ("first_name", "last_name")
        ),
        CheckConstraint(
            "phone IS NULL OR phone ~ '^(\\+[1-9][0-9]{2,14}|[0-9]{3,15})$'",
            name="ck_customer_phone_normalized",
        ),
        CheckConstraint(
            "email IS NULL OR (email <> '' AND email = btrim(email))",
            name="ck_customer_email_not_blank",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    is_archived: bool = Field(default=False, nullable=False)
