from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError
from sqlmodel import Session, create_engine

from atelier_api.settings import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

def get_session():
    try:
        with Session(engine) as session:
            yield session
    except (OperationalError, InterfaceError, TimeoutError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from None


SessionDep = Annotated[Session, Depends(get_session)]
