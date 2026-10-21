from fastapi import FastAPI
from contextlib import asynccontextmanager
from customers.router import customers_router
from health.router import health_router
from .settings import settings

app = FastAPI()

app.include_router(health_router)
app.include_router(customers_router)

@app.get("/")
async def root():
    return {"message": "Hello World"}




