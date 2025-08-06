from fastapi.testclient import TestClient

from bridge import app


def test_webapp_served() -> None:
    client = TestClient(app)
    resp = client.get("/webapp")
    assert resp.status_code == 200
    assert "Arianna Terminal" in resp.text
