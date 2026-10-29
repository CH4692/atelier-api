"""Share database connections and request-scoped sessions across features."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError
from sqlmodel import Session, create_engine

from atelier_api.settings import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)


def get_session() -> Iterator[Session]:
    """Provide a session and hide connection errors from API clients.

    Callers own transaction commits; leaving the context closes the session
    and rolls back uncommitted work.

    Yields:
        The session used by the current request.

    Raises:
        HTTPException: With status 503 for connection failures or pool timeouts.
    """
    try:
        with Session(engine) as session:
            yield session
    except OperationalError, InterfaceError, TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None


SessionDep = Annotated[Session, Depends(get_session)]
