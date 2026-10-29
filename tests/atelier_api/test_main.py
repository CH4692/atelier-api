import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

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
    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404


def test_development_keeps_api_documentation_available():
    app = create_app(Settings(_env_file=None, database_url="sqlite://"))
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"
    assert app.openapi_url == "/openapi.json"
    with TestClient(app) as client:
        response = client.get("/docs")
        assert response.status_code == 200
        assert 'id="login-form"' in response.text
        assert 'type="password"' in response.text
        assert 'id="session-logout"' in response.text
        assert 'url: "./openapi.json"' in response.text
        assert "requestInterceptor: (request) =>" in response.text
        assert 'request.headers["X-CSRF-Protection"] = "1"' in response.text
        assert 'request.credentials = "same-origin"' in response.text
        assert "url.origin === window.location.origin" in response.text
        assert 'request.headers["Origin"]' not in response.text
        definition = client.get("/openapi.json")
        assert definition.status_code == 200
        schema = definition.json()
        assert schema["openapi"].startswith("3.1.")
        assert "/api/v1/auth/login" in schema["paths"]
        assert "/api/v1/auth/me" in schema["paths"]
        assert "/docs" not in app.openapi()["paths"]


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


def test_swagger_interceptor_preserves_requests_and_defaults_missing_method_to_get():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the Swagger UI interceptor")
    app = create_app(Settings(_env_file=None, database_url="sqlite://"))
    with TestClient(app) as client:
        html = client.get("/docs").text
    script = re.search(r"<script>\s*([\s\S]*?)</script>", html)
    assert script is not None
    result = subprocess.run(
        [
            node,
            "-e",
            """
const assert = require("node:assert/strict");
const vm = require("node:vm");
const script = require("node:fs").readFileSync(0, "utf8");
for (const origin of ["http://127.0.0.1:8000", "http://localhost:8000"]) {
    let config;
    const SwaggerUIBundle = (value) => { config = value; };
    SwaggerUIBundle.presets = { apis: {} };
    vm.runInNewContext(script, {
        SwaggerUIBundle, URL,
        document: { getElementById: () => ({ addEventListener() {} }) },
        fetch: async () => ({ status: 401 }),
        window: { location: { origin, href: origin + "/docs" } }
    });
    for (const method of [undefined, "GET", "HEAD", "OPTIONS", "post", "PATCH", "DELETE"]) {
        const headers = { Accept: "application/json" };
        const request = { url: origin + "/api/v1/auth/logout", headers,
                          body: "payload", customProperty: {} };
        if (method !== undefined) request.method = method;
        const original = { ...request };
        assert.strictEqual(config.requestInterceptor(request), request);
        for (const key of Object.keys(original)) {
            assert.strictEqual(request[key], original[key]);
        }
        assert.strictEqual(request.method, method);
        assert.strictEqual(request.credentials, "same-origin");
        assert.strictEqual(headers.Origin, undefined);
        const unsafe = ["post", "PATCH", "DELETE"].includes(method);
        assert.strictEqual(headers["X-CSRF-Protection"], unsafe ? "1" : undefined);
    }
    const definition = { url: config.url, headers: {} };
    assert.strictEqual(config.requestInterceptor(definition), definition);
    assert.strictEqual(new URL(definition.url, origin + "/docs").href,
                       origin + "/openapi.json");
    assert.strictEqual(definition.headers["X-CSRF-Protection"], undefined);
}
""",
        ],
        input=script.group(1),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_swagger_login_logout_and_status_use_existing_session_endpoints():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the Swagger UI login controls")
    app = create_app(Settings(_env_file=None, database_url="sqlite://"))
    with TestClient(app) as client:
        html = client.get("/docs").text
    script = re.search(r"<script>\s*([\s\S]*?)</script>", html)
    assert script is not None
    result = subprocess.run(
        [node, str(Path(__file__).with_name("swagger_ui.cjs"))],
        input=script.group(1),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
