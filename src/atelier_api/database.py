from sqlmodel import create_engine, Session
from typing import Annotated
from fastapi import Depends
from atelier_api.settings import settings

engine = create_engine(settings.database_url)

def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]