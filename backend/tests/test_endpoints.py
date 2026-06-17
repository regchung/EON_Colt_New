"""端點整合測試:settings/roster 授權 + 手動指派生命週期 + apply-forecast dry-run。

需資料庫(CI 以 postgres service 提供)。寫入型測試自建資料並於 finally 清理,
唯讀/dry-run 測試在乾淨 DB(無歷史)也應回 200,不依賴特定資料。
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _admin_headers():
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------- 授權 ----------
def test_settings_requires_auth():
    assert client.get("/api/settings").status_code == 401


def test_settings_admin_ok():
    r = client.get("/api/settings", headers=_admin_headers())
    assert r.status_code == 200
    keys = {row["key"] for row in r.json()}
    assert "cost_per_vehicle_day" in keys
    assert "annual_service_days" in keys


def test_roster_patterns_requires_auth():
    assert client.get("/api/roster/patterns").status_code == 401


def test_roster_patterns_admin_ok():
    r = client.get("/api/roster/patterns", headers=_admin_headers())
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------- apply-forecast dry-run(不寫入;無資料時回 applied False) ----------
def test_apply_forecast_dry_run():
    r = client.post(
        "/api/roster/apply-forecast",
        params={"fleet": "台北", "dry_run": True},
        headers=_admin_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fleet"] == "台北"
    # 有歷史 → plan 7 天;無歷史 → applied False + reason
    if body.get("plan") is not None:
        assert len(body["plan"]) == 7
        assert body["applied"] is False  # dry_run 不寫入
    else:
        assert body["applied"] is False and body.get("reason")


# ---------- 手動指派生命週期(建立 → 指派 → 驗證 → 清理) ----------
def test_assign_order_lifecycle():
    h = _admin_headers()
    vid = oid = None
    try:
        v = client.post("/api/vehicles", json={"plate": "TEST-ASSIGN-1", "seats": 4}, headers=h)
        assert v.status_code in (200, 201), v.text
        vid = v.json()["id"]

        o = client.post("/api/orders", json={
            "service_date": "2026-06-20",
            "pickup_time": "2026-06-20T09:00:00",
            "pickup_address": "測試上車地",
            "dropoff_address": "測試下車地",
            "pax": 1,
        }, headers=h)
        assert o.status_code in (200, 201), o.text
        oid = o.json()["id"]

        a = client.post(f"/api/orders/{oid}/assign", params={"vehicle_id": vid}, headers=h)
        assert a.status_code == 200, a.text
        out = a.json()
        assert out["assigned_vehicle_id"] == vid
        assert out["status"] == "scheduled"
        assert out["dispatch_seq"] == 1
    finally:
        if oid is not None:
            client.delete(f"/api/orders/{oid}", headers=h)
        if vid is not None:
            client.delete(f"/api/vehicles/{vid}", headers=h)
