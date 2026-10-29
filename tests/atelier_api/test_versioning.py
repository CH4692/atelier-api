"""Verify API contract versioning and software release metadata."""

from importlib.metadata import version

from atelier_api.main import API_V1_PREFIX, app
from atelier_api.version import software_version


def test_business_routes_exist_only_under_api_v1():
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/customers",
        "/api/v1/customers/{customer_id}",
        "/api/v1/customers/{customer_id}/instruments",
        "/api/v1/instruments",
        "/api/v1/instruments/{instrument_id}",
    }
    assert expected <= paths
    assert (
        not {
            "/auth/login",
            "/auth/logout",
            "/auth/me",
            "/customers",
            "/customers/{customer_id}",
            "/instruments",
            "/instruments/{instrument_id}",
        }
        & paths
    )
    assert API_V1_PREFIX == "/api/v1"


def test_health_routes_remain_unversioned():
    paths = set(app.openapi()["paths"])
    assert {"/health/live", "/health/ready"} <= paths
    assert "/api/v1/health/live" not in paths
    assert "/api/v1/health/ready" not in paths


def test_openapi_uses_canonical_software_version_and_metadata():
    schema = app.openapi()
    assert software_version() == version("atelier-api")
    assert schema["info"] == {
        "title": "Atelier API",
        "summary": "Workshop Management API",
        "description": app.description,
        "version": version("atelier-api"),
    }
    assert schema["openapi"].startswith("3.1.")


def test_cookie_security_scheme_matches_backend_protection():
    schema = app.openapi()
    scheme = schema["components"]["securitySchemes"]["ServerSideSession"]
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "cookie"
    assert scheme["name"] == "dev-session"
    assert "security" not in schema["paths"]["/api/v1/auth/login"]["post"]
    assert "security" not in schema["paths"]["/health/live"]["get"]
    assert schema["paths"]["/api/v1/auth/me"]["get"]["security"] == [
        {"ServerSideSession": []}
    ]
    assert schema["paths"]["/api/v1/customers"]["get"]["security"] == [
        {"ServerSideSession": []}
    ]
