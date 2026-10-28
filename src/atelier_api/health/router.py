"""Expose process liveness and database connection readiness."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from atelier_api.database import SessionDep

health_router = APIRouter(prefix="/health")


@health_router.get(
    "/live",
    tags=["health"],
    summary="Check application liveness",
    response_model=dict[str, str],
)
async def health_check_live() -> dict[str, str]:
    """Confirm that the application responds without checking the database."""
    return {"status": "ok"}


@health_router.get(
    "/ready",
    tags=["health"],
    summary="Check database readiness",
    response_model=dict[str, str],
    responses={503: {"description": "Database connection unavailable"}},
)
async def health_check_readiness(session: SessionDep) -> dict[str, str]:
    """Check database connectivity without verifying the migration state.

    Raises:
        HTTPException: With status 503 if the database query fails.
    """
    try:
        session.exec(select(1)).first()
        return {"status": "ok", "database": "connected"}
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unavailable",
        )
