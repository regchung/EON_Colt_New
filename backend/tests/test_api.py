"""API 整合測試(需資料庫;CI 以 postgres service 提供)。"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_config_public():
    assert client.get("/api/config").status_code == 200


def test_protected_requires_auth():
    assert client.get("/api/orders").status_code == 401


def test_login_and_access():
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/orders", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).json()["username"] == "admin"


def test_bad_login():
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
