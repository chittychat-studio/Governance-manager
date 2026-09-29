from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_missing_user_404():
    assert client.get("/users/999999").status_code == 404
