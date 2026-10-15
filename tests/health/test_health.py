from fastapi.testclient import TestClient

from atelier_api.main import app

client = TestClient(app)

def test_health_check_ready():
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

def test_health_check_live():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
