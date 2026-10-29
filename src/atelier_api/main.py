"""Assemble protected workshop routes and public authentication/health endpoints."""

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from atelier_api.auth.dependencies import require_internal_user
from atelier_api.auth.router import router as auth_router
from atelier_api.customers.router import customers_router
from atelier_api.health.router import health_router
from atelier_api.instruments.customer_router import customer_instruments_router
from atelier_api.instruments.router import instruments_router
from atelier_api.settings import Settings, settings


class AuthenticationCacheHeaders(BaseHTTPMiddleware):
    """Prevent caching of authentication data and security failures."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/auth/") or response.status_code in {
            401,
            403,
            429,
        }:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response


def create_app(config: Settings | None = None) -> FastAPI:
    """Build an app with explicit origins and reusable workshop authorization."""
    config = config or settings
    application = FastAPI()
    application.state.settings = config
    application.add_middleware(AuthenticationCacheHeaders)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.frontend_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Protection"],
        expose_headers=["Retry-After"],
    )
    application.include_router(health_router)
    application.include_router(auth_router)
    protected = [Depends(require_internal_user)]
    for router in (customers_router, instruments_router, customer_instruments_router):
        application.include_router(router, dependencies=protected)

    @application.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        if request.url.path.startswith("/auth/"):
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        from fastapi.exception_handlers import request_validation_exception_handler

        return await request_validation_exception_handler(request, error)

    @application.get("/", summary="Get the API greeting", response_model=dict[str, str])
    async def root() -> dict[str, str]:
        return {"message": "Hello World"}

    return application


app = create_app()
