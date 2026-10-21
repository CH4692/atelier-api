from fastapi import APIRouter
from sqlmodel import text
from atelier_api.database import SessionDep

health_router = APIRouter(prefix="/health")

@health_router.get("/live", tags=["health"])
async def health_check_live():
    return {"status": "ok"}

@health_router.get("/ready",  tags=["health"])
async def health_check_readiness(session: SessionDep) -> dict[str, str]:
    try:
        session.exec(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Service unavailable",
    )