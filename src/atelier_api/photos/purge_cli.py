"""Run a disabled-by-default scheduled purge or a read-only eligibility preview."""

import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from time import monotonic
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from atelier_api.database import engine
from atelier_api.settings import settings

from .purge import purge_photos, retention_statistics
from .retention import utc_now
from .storage import R2Storage, StorageError


def batch_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Limit must be an integer") from None
    if not 1 <= limit <= 1000:
        raise argparse.ArgumentTypeError("Limit must be between 1 and 1000")
    return limit


def main() -> None:
    """Emit one JSON summary; exit nonzero on disabled or failed destructive runs."""
    parser = argparse.ArgumentParser(
        description="Purge expired, reviewed instrument photos"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read eligibility only; never connect to R2",
    )
    parser.add_argument("--limit", type=batch_limit, default=100)
    args = parser.parse_args()
    started = monotonic()
    execution_id = str(uuid4())
    storage: R2Storage | None = None
    try:
        if args.dry_run:
            namespace = (
                sha256(
                    f"{settings.r2_endpoint_url}/{settings.r2_bucket_name}".encode()
                ).hexdigest()
                if settings.photo_storage_enabled
                else None
            )
            with Session(engine) as session:
                summary = retention_statistics(session, settings, namespace, utc_now())
            summary.execution_id = execution_id
            summary.dry_run = True
            if summary.invalid_identity or summary.wrong_storage:
                summary.result = "failed"
            summary.duration_seconds = round(monotonic() - started, 3)
        else:
            if not settings.photo_auto_purge_enabled:
                raise ValueError("Automatic photo purging is disabled")
            storage = R2Storage(settings)
            summary = purge_photos(
                engine, storage, settings, limit=args.limit, execution_id=execution_id
            )
        print(json.dumps(asdict(summary), sort_keys=True))
        if summary.result != "success":
            raise SystemExit(1)
    except StorageError, SQLAlchemyError, ValueError:
        print(
            json.dumps(
                {
                    "result": "failed",
                    "execution_id": execution_id,
                    "error": "Photo purge unavailable; verify activation, direct database/storage configuration and retry",
                    "duration_seconds": round(monotonic() - started, 3),
                }
            )
        )
        raise SystemExit(1) from None
    finally:
        if storage is not None:
            storage.close()
