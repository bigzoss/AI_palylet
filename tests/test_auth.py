import time

from fastapi.testclient import TestClient

from backend.auth import attempts, sessions
from backend.config import settings
from backend.main import app


def test_login_and_protected_resources():
    attempts.clear()
    with TestClient(app) as guest:
        for path in [
            "/api/v1/projects",
            "/api/v1/health",
            "/api/v1/media/private/content",
            "/api/v1/exports/private/download",
        ]:
            assert guest.get(path).status_code == 401
        assert (
            guest.post("/api/v1/auth/login", json={"username": "test-admin", "password": "wrong"}).status_code
            == 401
        )
        result = guest.post(
            "/api/v1/auth/login", json={"username": "test-admin", "password": "test-password-only"}
        )
        assert result.status_code == 200
        assert "HttpOnly" in result.headers["set-cookie"]
        assert "SameSite=strict" in result.headers["set-cookie"]
        assert guest.get("/api/v1/auth/me").json()["username"] == "test-admin"
        assert guest.get("/api/v1/projects").status_code == 200
        cookie = guest.cookies.get("framecraft_session")
        assert guest.post("/api/v1/auth/logout").status_code == 200
        guest.cookies.set("framecraft_session", cookie)
        assert guest.get("/api/v1/projects").status_code == 401


def test_expired_session(client):
    for key, (username, _) in list(sessions.items()):
        sessions[key] = (username, time.time() - 1)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_missing_password_denies_login(monkeypatch):
    monkeypatch.setattr(settings, "auth_password", "")
    with TestClient(app) as guest:
        assert guest.post("/api/v1/auth/login", json={"username": "admin", "password": ""}).status_code == 503


def test_login_rate_limit():
    attempts.clear()
    with TestClient(app) as guest:
        for _ in range(10):
            assert (
                guest.post("/api/v1/auth/login", json={"username": "x", "password": "x"}).status_code == 401
            )
        assert guest.post("/api/v1/auth/login", json={"username": "x", "password": "x"}).status_code == 429
    attempts.clear()
