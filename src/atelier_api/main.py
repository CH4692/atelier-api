"""Assemble protected workshop routes and public authentication/health endpoints."""

from collections.abc import Iterator

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from atelier_api.audit.router import router as audit_router
from atelier_api.auth.dependencies import get_current_user, require_internal_user
from atelier_api.auth.router import router as auth_router
from atelier_api.customers.router import customers_router
from atelier_api.docs import swagger_ui
from atelier_api.health.router import health_router
from atelier_api.instruments.customer_router import customer_instruments_router
from atelier_api.instruments.qr import router as qr_router
from atelier_api.instruments.qr import scan_router
from atelier_api.instruments.router import instruments_router
from atelier_api.photos.router import router as photos_router
from atelier_api.repair_orders.router import router as repairs_router
from atelier_api.settings import Settings, settings
from atelier_api.version import software_version

API_V1_PREFIX = "/api/v1"


class AuthenticationCacheHeaders(BaseHTTPMiddleware):
    """Prevent caching of account/audit data and security failures."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        if (
            request.url.path.startswith(
                (f"{API_V1_PREFIX}/auth/", f"{API_V1_PREFIX}/audit-events")
            )
            or "/photos" in request.url.path
            or response.status_code
            in {
                401,
                403,
                429,
            }
        ):
            response.headers["Cache-Control"] = (
                "private, no-store" if "/photos" in request.url.path else "no-store"
            )
            response.headers["Pragma"] = "no-cache"
        return response


PUBLIC_OPERATIONS = {
    ("GET", "/"),
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
    ("POST", f"{API_V1_PREFIX}/auth/login"),
    ("POST", f"{API_V1_PREFIX}/auth/logout"),
}


def _uses_dependency(dependant: Dependant, dependency: object) -> bool:
    """Find a security dependency throughout FastAPI's dependency tree."""
    return dependant.call is dependency or any(
        _uses_dependency(child, dependency) for child in dependant.dependencies
    )


def _access_policies(
    application: FastAPI,
) -> Iterator[tuple[str, set[str], Dependant]]:
    """Yield concrete routes across eager and lazily included FastAPI routers."""
    for route in application.routes:
        if isinstance(route, APIRoute):
            yield route.path, route.methods or set(), route.dependant
            continue
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is None:
            continue
        for context in contexts():
            yield context.path, context.methods or set(), context.dependant


def enforce_default_deny(application: FastAPI) -> None:
    """Reject routes that are neither explicitly public nor session protected."""
    for path, methods, dependant in _access_policies(application):
        public_methods = {
            method for method in methods if (method, path) in PUBLIC_OPERATIONS
        }
        if public_methods == methods:
            continue
        if not _uses_dependency(dependant, get_current_user):
            operations = ", ".join(sorted(methods - public_methods))
            raise RuntimeError(
                f"Route {operations} {path} has no authentication dependency"
            )


def create_app(config: Settings | None = None) -> FastAPI:
    """Build an app with explicit origins and reusable workshop authorization."""
    config = config or settings
    documentation_url = "/docs" if config.api_documentation_enabled else None
    application = FastAPI(
        title="Atelier API",
        summary="Workshop Management API",
        description=(
            "Manage workshop customers and instruments through the versioned v1 API. "
            "Browser authentication uses opaque PostgreSQL-backed session cookies; "
            "internal resources require an administrator or employee account. API "
            "contract versions are independent from this software release version."
        ),
        version=software_version(),
        docs_url=None,
        redoc_url="/redoc" if config.api_documentation_enabled else None,
        openapi_url="/openapi.json" if config.api_documentation_enabled else None,
    )
    if documentation_url is not None:
        application.docs_url = documentation_url
        application.add_route(documentation_url, swagger_ui, include_in_schema=False)
    application.state.settings = config
    application.add_middleware(AuthenticationCacheHeaders)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.frontend_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Protection"],
        expose_headers=["Retry-After", "X-Total-Count"],
    )
    application.include_router(health_router)
    api_v1_router = APIRouter(prefix=API_V1_PREFIX)
    api_v1_router.include_router(auth_router)
    api_v1_router.include_router(audit_router)
    protected = [Depends(require_internal_user)]
    for router in (
        customers_router,
        instruments_router,
        customer_instruments_router,
        repairs_router,
        photos_router,
        qr_router,
    ):
        api_v1_router.include_router(router, dependencies=protected)
    application.include_router(api_v1_router)
    application.include_router(scan_router, dependencies=protected)

    @application.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        if request.url.path.startswith(f"{API_V1_PREFIX}/auth/"):
            return JSONResponse({"detail": "Invalid request"}, status_code=422)
        from fastapi.exception_handlers import request_validation_exception_handler

        return await request_validation_exception_handler(request, error)

    @application.get("/", summary="Get the API greeting", response_model=dict[str, str])
    async def root() -> dict[str, str]:
        return {"message": "Hello World"}

    enforce_default_deny(application)
    return application


app = create_app()
