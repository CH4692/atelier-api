"""Define the account roles supported by the application."""

from enum import StrEnum


class UserRole(StrEnum):
    """Distinguish workshop administrators, employees and future portal users."""

    ADMIN = "admin"
    EMPLOYEE = "employee"
    CUSTOMER = "customer"
