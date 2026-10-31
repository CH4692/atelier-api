"""Reconcile abandoned uploads without deleting retained photo evidence."""

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from atelier_api.database import engine
from atelier_api.settings import settings

from .service import cleanup_abandoned_uploads
from .storage import R2Storage, StorageError


def main() -> None:
    """Retry up to 100 abandoned pending uploads older than 24 hours."""
    storage: R2Storage | None = None
    try:
        storage = R2Storage(settings)
        with Session(engine) as session:
            count = cleanup_abandoned_uploads(session, storage)
        print(f"Reconciled {count} abandoned photo uploads. Retained photos unchanged.")
    except StorageError, SQLAlchemyError:
        raise SystemExit(
            "Photo reconciliation unavailable; verify configuration and retry."
        ) from None
    finally:
        if storage is not None:
            storage.close()
