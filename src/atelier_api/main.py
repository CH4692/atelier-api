
from fastapi import FastAPI

from atelier_api.customers.router import customers_router
from atelier_api.health.router import health_router

app = FastAPI()

app.include_router(health_router)
app.include_router(customers_router)

@app.get("/")
async def root():
    return {"message": "Hello World"}




