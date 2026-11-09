"""Seed only an explicitly selected disposable development database."""

import argparse
import json
import os
import sys
from dataclasses import asdict, replace
from datetime import date, datetime
from getpass import getpass
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import SecretStr, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, create_engine

from atelier_api.photos.storage import R2Storage, StorageError
from atelier_api.settings import Settings, settings

from .data import PROFILE, UNAVAILABLE, build_small
from .photos import seed_photos
from .service import SEED_LOCK, SeedReport, guard_target, seed_small


def main(argv: list[str] | None = None) -> None:
    """Print a plan or seed with a separate target URL and explicit confirmation."""
    parser = argparse.ArgumentParser(
        description="Seed fictional Atelier workshop data into an empty development PostgreSQL database."
    )
    parser.add_argument("--profile", choices=["small"], default="small")
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        help="Reference date, YYYY-MM-DD; existing datasets retain their original date",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the plan without opening database/storage connections",
    )
    parser.add_argument(
        "--confirm-demo-data",
        action="store_true",
        help="Confirm the explicitly configured database is disposable demo/test data",
    )
    parser.add_argument(
        "--with-photos",
        action="store_true",
        help="Upload 50 synthetic illustrations to the existing private R2 demo/test bucket",
    )
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            plan = build_small(
                args.as_of or datetime.now(ZoneInfo("Europe/Berlin")).date()
            )
            report = SeedReport(
                PROFILE,
                plan.as_of,
                False,
                {
                    "customers": len(plan.customers),
                    "instruments": len(plan.instruments),
                    "repairs": len(plan.repairs),
                    "documents": 30,
                    "users": 6,
                    "internal_users": 5,
                    "portal_users": 1,
                    "templates": 12,
                    "repair_items": 210,
                    "estimates": 25,
                    "photos": 50 if args.with_photos else 0,
                    "rentals": 0,
                    "invoices": 0,
                    "payments": 0,
                },
            )
        else:
            target = os.environ.get("ARTELIER_DEMO_DATABASE_URL")
            if not target or not args.confirm_demo_data:
                raise ValueError(
                    "Set ARTELIER_DEMO_DATABASE_URL and pass --confirm-demo-data; DATABASE_URL is never used as a seed target."
                )
            config = Settings.model_validate(
                settings.model_dump() | {"database_url": target}
            )
            guard_target(config)
            if args.with_photos and (
                not config.photo_storage_enabled
                or not (config.r2_bucket_name or "").endswith(("-demo", "-test"))
            ):
                raise ValueError(
                    "Photos require configured private R2 storage with a bucket name ending in -demo or -test."
                )
            password_value = os.environ.get("ARTELIER_DEMO_PASSWORD")
            if password_value is None and sys.stdin.isatty():
                password_value = getpass("Password for fictional demo accounts: ")
                if password_value != getpass("Repeat password: "):
                    raise ValueError("Passwords do not match.")
            password = SecretStr(password_value) if password_value is not None else None
            engine = create_engine(
                config.database_url, pool_pre_ping=True, hide_parameters=True
            )
            try:
                with engine.connect() as connection:
                    # Serialize the database phase and subsequent nontransactional photo uploads.
                    connection.execute(
                        text("SELECT pg_advisory_lock(:key)"), {"key": SEED_LOCK}
                    )
                    connection.commit()
                    try:
                        with connection.begin():
                            report = seed_small(
                                connection, config, password=password, as_of=args.as_of
                            )
                        if args.with_photos:
                            storage = R2Storage(config)
                            try:
                                with Session(bind=connection) as session:
                                    count = seed_photos(session, config, storage)
                                report = replace(
                                    report, counts=report.counts | {"photos": count}
                                )
                            finally:
                                storage.close()
                    finally:
                        connection.rollback()
                        connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": SEED_LOCK}
                        )
                        connection.commit()
            finally:
                engine.dispose()
        if args.dry_run:
            report = replace(report, dry_run=True)
        if not args.with_photos:
            report = replace(
                report,
                limitations=(
                    *UNAVAILABLE,
                    "Fotos: nicht angefordert; --with-photos benötigt den vorhandenen privaten R2-Demospeicher.",
                ),
            )
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2, default=str))
    except ValidationError:
        parser.exit(
            1,
            "Invalid demo configuration or account password policy violation. No credentials are printed.\n",
        )
    except SQLAlchemyError:
        parser.exit(
            1,
            "Demo database operation failed. Check the dedicated target and existing Alembic migrations; the database phase rolls back on failure.\n",
        )
    except HTTPException:
        parser.exit(
            1,
            "Demo operation was rejected by existing backend rules. Database changes roll back during the database phase; photo uploads can be resumed.\n",
        )
    except StorageError:
        parser.exit(
            1,
            "Demo photo storage failed. Database data is retained; retry with the same target and inspect pending upload recovery.\n",
        )
    except (ValueError, LookupError, PermissionError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
