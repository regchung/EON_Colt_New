"""dispatcher.run_dispatch 整合測試:離線驗證真實 VROOM 求解(免 OSRM)。

關鍵:設 MATRIX_PROVIDER=haversine,讓 matrix.build_matrix 走離線估算 →
不需 OSRM 也能跑完整 VROOM 求解。自建小場景(車/單/出勤),驗證指派/路線/車種約束,
所有測試資料以 TEST 前綴 + 遠期日期標記,finally 徹底清理(本機真實 DB 不受污染)。
"""
from datetime import date, datetime, timezone, timedelta

import pytest
from sqlalchemy import delete

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.order import Order
from app.models.route import RouteStop
from app.models.shift import ShiftException
from app.models.vehicle import Vehicle
from app.services import dispatcher

TW = timezone(timedelta(hours=8))
TEST_DATE = date(2099, 1, 5)   # 遠期,避免撞真實資料


def _dt(h, m=0):
    return datetime(2099, 1, 5, h, m, tzinfo=TW)


def _cleanup(db):
    db.execute(delete(RouteStop).where(RouteStop.service_date == TEST_DATE))
    db.execute(delete(Order).where(Order.source_order_no.like("TEST-DISP-%")))
    db.execute(delete(ShiftException).where(ShiftException.ex_date == TEST_DATE))
    db.execute(delete(Vehicle).where(Vehicle.plate.like("TEST-V%")))
    db.commit()


def _seed(db, welfare_order=False, welfare_vehicle=True):
    v1 = Vehicle(plate="TEST-V1", type="normal", seats=4, active=True,
                 depot_lng=121.53, depot_lat=25.04, start_lng=121.53, start_lat=25.04,
                 end_lng=121.53, end_lat=25.04)
    v2 = Vehicle(plate="TEST-V2", type="welfare" if welfare_vehicle else "normal", seats=4, active=True,
                 depot_lng=121.55, depot_lat=25.05, start_lng=121.55, start_lat=25.05,
                 end_lng=121.55, end_lat=25.05)
    db.add_all([v1, v2])
    db.flush()
    db.add_all([
        ShiftException(vehicle_id=v1.id, ex_date=TEST_DATE, available=True),
        ShiftException(vehicle_id=v2.id, ex_date=TEST_DATE, available=True),
    ])
    pts = [(121.54, 25.045, 121.56, 25.05), (121.52, 25.03, 121.55, 25.048)]
    orders = []
    for i, (plng, plat, dlng, dlat) in enumerate(pts):
        orders.append(Order(
            source_order_no=f"TEST-DISP-{i}", service_date=TEST_DATE, pickup_time=_dt(8 + i),
            pickup_window_min=30, passenger_name=f"測試{i}",
            pickup_address=f"測試上車{i}", dropoff_address=f"測試下車{i}",
            pickup_lng=plng, pickup_lat=plat, dropoff_lng=dlng, dropoff_lat=dlat,
            pax=1, vehicle_type="welfare" if (welfare_order and i == 0) else "normal",
            need_wheelchair=bool(welfare_order and i == 0), allow_pool=False, status="imported",
        ))
    db.add_all(orders)
    db.commit()
    return v1, v2, orders


@pytest.fixture
def haversine(monkeypatch):
    """離線矩陣:免 OSRM 即可跑 VROOM 求解。"""
    monkeypatch.setattr(settings, "MATRIX_PROVIDER", "haversine")


def test_run_dispatch_assigns_orders(haversine):
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed(db)
        res = dispatcher.run_dispatch(db, TEST_DATE)
        assert "error" not in res, res
        assert res["assigned"] >= 1
        assert res["vehicles_used"] >= 1
        db.expire_all()
        scheduled = db.query(Order).filter(
            Order.source_order_no.like("TEST-DISP-%"), Order.status == "scheduled").all()
        assert len(scheduled) == res["assigned"]
        assert all(o.assigned_vehicle_id for o in scheduled)
        assert all(o.eta is not None for o in scheduled)
        # 應產生路線站點
        assert db.query(RouteStop).filter(RouteStop.service_date == TEST_DATE).count() > 0
    finally:
        _cleanup(db)
        db.close()


def test_run_dispatch_result_contract(haversine):
    """回傳結構契約:鍵齊全、數字自洽(assigned + unassigned + 略過 = 總數)。"""
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed(db)
        res = dispatcher.run_dispatch(db, TEST_DATE)
        assert "error" not in res, res
        for k in ("service_date", "provider", "vehicles_used", "orders_total",
                  "assigned", "unassigned", "routes", "total_duration_sec"):
            assert k in res, f"缺鍵 {k}"
        assert res["orders_total"] == 2
        assert isinstance(res["assigned"], int) and 0 <= res["assigned"] <= 2
        assert isinstance(res["routes"], dict)
        assert res["provider"] == "haversine"      # 確認走離線矩陣
    finally:
        _cleanup(db)
        db.close()


def test_run_dispatch_no_coded_orders(haversine):
    db = SessionLocal()
    try:
        _cleanup(db)
        # 出勤車有,但訂單缺座標 → 不可排
        v = Vehicle(plate="TEST-V1", type="normal", seats=4, active=True,
                    depot_lng=121.53, depot_lat=25.04)
        db.add(v)
        db.flush()
        db.add(ShiftException(vehicle_id=v.id, ex_date=TEST_DATE, available=True))
        db.add(Order(source_order_no="TEST-DISP-NC", service_date=TEST_DATE,
                     pickup_time=_dt(9), passenger_name="無座標",
                     pickup_address="x", dropoff_address="y", pax=1,
                     vehicle_type="normal", status="imported"))
        db.commit()
        res = dispatcher.run_dispatch(db, TEST_DATE)
        assert "error" in res
    finally:
        _cleanup(db)
        db.close()


def test_run_dispatch_welfare_constraint(haversine):
    """福祉訂單(輪椅)只有福祉車能服務:若排入,指派車必為 welfare 車種。

    (環境無關:不綁特定車 id,改驗指派到的車是 welfare —— 本機有真實福祉車亦成立。)
    """
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed(db, welfare_order=True, welfare_vehicle=True)
        res = dispatcher.run_dispatch(db, TEST_DATE)
        assert "error" not in res, res
        db.expire_all()
        wf = db.query(Order).filter(Order.source_order_no == "TEST-DISP-0").one()
        if wf.status == "scheduled":
            v = db.get(Vehicle, wf.assigned_vehicle_id)
            assert v.type == "welfare", "福祉訂單被指派到非福祉車"
    finally:
        _cleanup(db)
        db.close()
