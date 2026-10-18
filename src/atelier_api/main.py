from fastapi import FastAPI
from health.router import health_router
from customers.router import customers_router

app = FastAPI()

app.include_router(health_router)
app.include_router(customers_router)

@app.get("/")
async def root():
    return {"message": "Hello World"}

