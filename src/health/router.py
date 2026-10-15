from fastapi import APIRouter

health_router = APIRouter(prefix="/health")

@health_router.get("/live", tags=["health"])
async def health_check_live():
    return {"status": "ok"}

@health_router.get("/ready",  tags=["health"])
async def health_check_ready():
    return {"status": "ready"}