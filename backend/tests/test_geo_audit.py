"""地址編碼勘誤(geo_audit)測試:純函式 + 以 mock provider 驗證離群座標自動校正。"""
from datetime import date, datetime, timezone, timedelta

from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models.order import Order
from app.services import geo_audit

TW = timezone(timedelta(hours=8))
TEST_DATE = date(2099, 2, 2)


def _cleanup(db):
    db.execute(delete(Order).where(Order.source_order_no.like("TEST-GA-%")))
    db.commit()


def test_clean_and_facility():
    assert geo_audit._clean("中正區常德街I號(台大醫院門口)") == "中正區常德街1號"
    assert geo_audit._clean("泰山區明志路二段136巷24號(1樓)") == "泰山區明志路二段136巷24號"
    assert geo_audit._facility("中正區常德街巷1號(台大醫院門口)") == "台大醫院"
    assert geo_audit._facility("大安區建國南路一段291巷14號") is None


def test_variants_prepend_city_when_missing():
    vs = geo_audit._variants("中正區常德街1號", ["臺北市", "新北市"])
    assert any(v.startswith("臺北市") for v in vs)
    assert "中正區常德街1號" in vs


def test_km_zero_same_point():
    assert geo_audit._km(121.5, 25.0, 121.5, 25.0) < 1e-6


def _seed(db):
    """台北營運區數筆正常單 + 1 筆上車座標被誤編到中南部的離群單。"""
    good = [(121.53, 25.04), (121.55, 25.05), (121.54, 25.045)]
    for i, (lng, lat) in enumerate(good):
        db.add(Order(source_order_no=f"TEST-GA-G{i}", service_date=TEST_DATE,
                     pickup_time=datetime(2099, 2, 2, 9, tzinfo=TW), passenger_name=f"好{i}",
                     pickup_address=f"台北市中正區好路{i}號", dropoff_address="台北市大安區X",
                     pickup_lng=lng, pickup_lat=lat, dropoff_lng=121.54, dropoff_lat=25.03,
                     pax=1, vehicle_type="normal", status="done", fleet="台北"))
    # 離群:上車被編到 (120.2, 23.8)(中南部,>150km)
    db.add(Order(source_order_no="TEST-GA-BAD", service_date=TEST_DATE,
                 pickup_time=datetime(2099, 2, 2, 9, tzinfo=TW), passenger_name="離群客",
                 pickup_address="中正區常德街I號(台大醫院門口)", dropoff_address="台北市大安區Y",
                 pickup_lng=120.2175, pickup_lat=23.7987, dropoff_lng=121.538, dropoff_lat=25.038,
                 pax=1, vehicle_type="normal", status="done", fleet="台北"))
    db.commit()


def test_audit_day_corrects_outlier(monkeypatch):
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed(db)

        # mock provider:含「常德街」的查詢回台北正確座標;其餘回 None
        def fake_provider(addr):
            if "常德街" in addr:
                return {"lng": 121.5172, "lat": 25.0414, "precision": "approx",
                        "formatted": "臺北市中正區常德街1號"}
            return None
        monkeypatch.setattr(geo_audit, "_provider_geocode", fake_provider)

        rep = geo_audit.audit_day(db, TEST_DATE, apply=True)
        assert rep["corrected_count"] == 1, rep
        c = rep["corrected"][0]
        assert c["side"] == "pickup" and c["reason"] == "離群"
        assert c["new"][0] == 121.5172

        db.expire_all()
        bad = db.query(Order).filter(Order.source_order_no == "TEST-GA-BAD").one()
        assert abs(bad.pickup_lng - 121.5172) < 1e-4, "離群上車座標應已被校正回台北"
        assert abs(bad.pickup_lat - 25.0414) < 1e-4
    finally:
        _cleanup(db)
        db.close()


def test_audit_day_dry_run_does_not_write(monkeypatch):
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed(db)
        monkeypatch.setattr(geo_audit, "_provider_geocode",
                            lambda a: {"lng": 121.5172, "lat": 25.0414} if "常德街" in a else None)
        rep = geo_audit.audit_day(db, TEST_DATE, apply=False)
        assert rep["corrected_count"] == 1
        db.expire_all()
        bad = db.query(Order).filter(Order.source_order_no == "TEST-GA-BAD").one()
        assert abs(bad.pickup_lng - 120.2175) < 1e-3, "dry-run 不應回寫座標"
    finally:
        _cleanup(db)
        db.close()
