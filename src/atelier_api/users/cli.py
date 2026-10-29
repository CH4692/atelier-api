"""Provision accounts through explicit, local administrative commands."""

import argparse
import sys
from getpass import getpass

from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from atelier_api.database import engine

from .authentication import authenticate_user, require_active_user
from .roles import UserRole
from .schemas import UserCreate
from .service import (
    bootstrap_admin,
    create_user,
    set_customer_association,
    set_user_active,
    set_user_role,
)


def _password() -> str:
    password = getpass("New account password: ")
    if password != getpass("Repeat password: "):
        raise ValueError("Passwords do not match")
    return password


def main() -> None:
    """Run provisioning with password prompts instead of command-line secrets."""
    parser = argparse.ArgumentParser(description="Manage Atelier application users.")
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser(
        "bootstrap", help="Create the initial administrator once"
    )
    bootstrap.add_argument("--email", required=True)
    create = commands.add_parser("create")
    create.add_argument("--email", required=True)
    create.add_argument("--role", choices=list(UserRole), default=UserRole.EMPLOYEE)
    create.add_argument("--customer-id", type=int)
    for command in ("activate", "deactivate", "set-role", "associate"):
        child = commands.add_parser(command)
        child.add_argument("user_id", type=int)
        if command == "set-role":
            child.add_argument("role", choices=list(UserRole))
        if command == "associate":
            group = child.add_mutually_exclusive_group(required=True)
            group.add_argument("--customer-id", type=int)
            group.add_argument("--clear", action="store_true")
    for name, child in commands.choices.items():
        if name != "bootstrap":
            child.add_argument("--admin-email", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.exit(1, "An interactive terminal is required for password prompts.\n")
    try:
        with Session(engine) as session:
            if args.command == "bootstrap":
                result = bootstrap_admin(
                    UserCreate(email=args.email, password=SecretStr(_password())),
                    session,
                )
            else:
                actor = authenticate_user(
                    args.admin_email, getpass("Administrator password: "), session
                )
                if (
                    actor is None
                    or require_active_user(actor, session).role != UserRole.ADMIN
                ):
                    raise PermissionError("Administrator authentication failed")
                if args.command == "create":
                    result = create_user(
                        UserCreate(email=args.email, password=SecretStr(_password())),
                        session,
                        actor=actor,
                        role=UserRole(args.role),
                        customer_id=args.customer_id,
                    )
                elif args.command in ("activate", "deactivate"):
                    result = set_user_active(
                        args.user_id, args.command == "activate", session, actor=actor
                    )
                elif args.command == "set-role":
                    result = set_user_role(
                        args.user_id, UserRole(args.role), session, actor=actor
                    )
                else:
                    result = set_customer_association(
                        args.user_id, args.customer_id, session, actor=actor
                    )
            print(result.model_dump_json())
    except SQLAlchemyError:
        parser.exit(
            1, "Database operation failed; check connectivity and migrations.\n"
        )
    except ValidationError:
        parser.exit(1, "Invalid account details or password policy violation.\n")
    except (PermissionError, LookupError, ValueError) as error:
        parser.exit(1, f"{error}\n")
