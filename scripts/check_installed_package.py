"""Run with the wheel-installed Python interpreter, outside the source tree."""

import importlib
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path


def main() -> None:
    """Verify installed modules, OpenAPI routes, liveness and the CLI target."""
    package = distribution("atelier-api")
    # Check every shipped application module, including the nested packages.
    for file in package.files or []:
        if file.parts[0] == "atelier_api" and file.suffix == ".py":
            parts = list(file.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            module = importlib.import_module(".".join(parts))
            assert module.__file__ is not None
            assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix))

    from fastapi.testclient import TestClient

    from atelier_api.main import app

    routes = set(app.openapi()["paths"])
    assert {
        "/auth/login",
        "/auth/logout",
        "/auth/me",
        "/customers",
        "/customers/{customer_id}",
        "/customers/{customer_id}/instruments",
        "/health/live",
        "/health/ready",
        "/instruments",
        "/instruments/{instrument_id}",
    } <= routes
    with TestClient(app) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert client.get("/auth/me").status_code == 401
        assert client.get("/instruments").status_code == 401

    entrypoint = next(ep for ep in package.entry_points if ep.name == "atelier-api")
    assert callable(entrypoint.load())
    cleanup = next(
        ep for ep in package.entry_points if ep.name == "atelier-sessions-cleanup"
    )
    assert callable(cleanup.load())
    subprocess.run(
        [str(Path(sys.executable).parent / "atelier-api"), "--help"], check=True
    )
    print("Installed wheel: all modules, application routes and CLI verified.")


if __name__ == "__main__":
    main()
