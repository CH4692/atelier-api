"""Assemble the FastAPI application and register feature routers."""

from fastapi import FastAPI

from atelier_api.customers.router import customers_router
from atelier_api.health.router import health_router
from atelier_api.instruments.customer_router import customer_instruments_router
from atelier_api.instruments.router import instruments_router

app = FastAPI()

app.include_router(health_router)
app.include_router(customers_router)
app.include_router(instruments_router)
app.include_router(customer_instruments_router)


@app.get("/", summary="Get the API greeting", response_model=dict[str, str])
async def root() -> dict[str, str]:
    """Return the API greeting without querying the database."""
    return {"message": "Hello World"}
