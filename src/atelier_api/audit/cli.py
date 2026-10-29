"""Apply audit retention through a trusted database operator command."""

from sqlmodel import Session

from atelier_api.database import engine
from atelier_api.settings import settings

from .service import purge_expired_events


def main() -> None:
    """Purge expired events without printing personal data or individual records."""
    with Session(engine) as session:
        count = purge_expired_events(session, settings.audit_retention_days)
    print(f"Removed {count} expired audit events.")
