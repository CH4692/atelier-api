import pytest

pytestmark = pytest.mark.integration


def test_readiness_with_postgresql(postgres_client):
    response = postgres_client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
