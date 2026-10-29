import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from atelier_api.main import create_app, enforce_default_deny
from atelier_api.settings import Settings


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


def test_production_disables_public_api_documentation():
    app = create_app(
        Settings(
            _env_file=None,
            database_url="sqlite://",
            environment="production",
            frontend_origins=["https://app.example.test"],
        )
    )
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_development_keeps_api_documentation_available():
    app = create_app(Settings(_env_file=None, database_url="sqlite://"))
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"


def test_default_deny_rejects_an_unprotected_business_route():
    app = FastAPI()

    @app.get("/future-business-resource")
    def exposed_resource() -> dict[str, bool]:
        return {"exposed": True}

    with pytest.raises(RuntimeError, match="has no authentication dependency"):
        enforce_default_deny(app)


def test_every_nonpublic_application_route_uses_shared_authentication():
    app = create_app(Settings(_env_file=None, database_url="sqlite://"))
    # create_app performs the same check at startup. This explicit regression test
    # gives contributors a focused failure when a new router omits protection.
    enforce_default_deny(app)
    assert any(isinstance(route, APIRoute) for route in app.routes)
