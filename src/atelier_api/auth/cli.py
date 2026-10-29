"""Clean up expired authentication records through an operator command."""

from sqlmodel import Session

from atelier_api.database import engine
from atelier_api.settings import settings

from .service import cleanup_expired_sessions


def main() -> None:
    """Delete unusable sessions without printing tokens or account identifiers."""
    with Session(engine) as session:
        count = cleanup_expired_sessions(session, settings)
    print(f"Removed {count} expired or revoked sessions.")
