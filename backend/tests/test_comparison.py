"""comparison / pool_suggest 整合測試(離線 haversine,免 OSRM)。

兩者皆透過 matrix.build_matrix 取車程 → 設 MATRIX_PROVIDER=haversine 即可離線跑求解。
測試資料以 TESTFLEET / RTEST 前綴 + 遠期日期標記,finally 徹底清理。
"""
from datetime import date, datetime, timezone, timedelta

import pytest
from sqlalchemy import delete

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.dispatch_history import DispatchHistory
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import comparison, pool_suggest

TW = timezone(timedelta(hours=8))
TEST_DATE = date(2099, 2, 9)
FLEET = "TESTFLEET"
SERVED = "已轉至正式單"


def _dt(h, m=0):
    return datetime(2099, 2, 9, h, m, tzinfo=TW)


@pytest.fixture
def haversine(monkeypatch):
    monkeypatch.setattr(settings, "MATRIX_PROVIDER", "haversine")


def _cleanup(db):
    db.execute(delete(Order).where(Order.source_order_no.like("TEST-CMP-%")))
    db.execute(delete(DispatchHistory).where(DispatchHistory.source_order_no.like("TEST-CMP-%")))
    db.execute(delete(Vehicle).where(Vehicle.plate.like("RTEST-CMP%")))
    db.commit()


def _seed(db):
    v = Vehicle(plate="RTEST-CMP1", type="normal", seats=4, active=True, home_fleet=FLEET,
                depot_lng=121.53, depot_lat=25.04, start_lng=121.53, start_lat=25.04,
                end_lng=121.53, end_lat=25.04)
    db.add(v)
    db.flush()
    pts = [(121.54, 25.045, 121.56, 25.05), (121.52, 25.03, 121.55, 25.048)]
    for i, (plng, plat, dlng, dlat) in enumerate(pts):
        db.add(Order(
            source_order_no=f"TEST-CMP-{i}", fleet=FLEET, service_date=TEST_DATE, pickup_time=_dt(8 + i),
            pickup_window_min=30, passenger_name=f"對比{i}",
            pickup_address=f"上車{i}", dropoff_address=f"下車{i}",
            pickup_lng=plng, pickup_lat=plat, dropoff_lng=dlng, dropoff_lat=dlat,
            pax=1, vehicle_type="normal", allow_pool=False, status="done"))
        db.add(DispatchHistory(
            source_order_no=f"TEST-CMP-{i}", fleet=FLEET, service_date=TEST_DATE,
            pickup_time=_dt(8 + i), plate="RTEST-CMP1", status=SERVED))
    db.commit()
    return v


# ---------- comparison ----------
def test_compare_day_no_data_returns_none(haversine):
    db = SessionLocal()
    try:
        _cleanup(db)
        assert comparison.compare_day(db, "不存在的車行XYZ", TEST_DATE) is None
    finally:
        _cleanup(db)
        db.close()


def test_compare_day_integration(haversine):
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed(db)
        res = comparison.compare_day(db, FLEET, TEST_DATE)
        assert res is not None, "有成行單 + 人工派遣紀錄,compare_day 不應回 None"
        for k in ("human_vehicles", "vroom_vehicles", "vroom_unassigned", "saved_vehicles"):
            assert k in res, f"缺鍵 {k}"
        assert res["human_vehicles"] == 1                    # 人工只用 1 台(1 個車牌)
        assert res["vroom_vehicles"] >= 1
        assert res["saved_vehicles"] == res["human_vehicles"] - res["vroom_vehicles"]
    finally:
        _cleanup(db)
        db.close()


# ---------- pool_suggest ----------
def test_pool_suggest_no_data_returns_none(haversine):
    db = SessionLocal()
    try:
        _cleanup(db)
        assert pool_suggest.suggest_day(db, "不存在的車行XYZ", TEST_DATE) is None
    finally:
        _cleanup(db)
        db.close()
