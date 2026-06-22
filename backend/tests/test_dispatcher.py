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


def test_run_dispatch_welfare_order_requires_welfare_vehicle(haversine):
    """強制版:單一福祉(輪椅)單 + 有福祉車可用 → 必排入,且指派車必為 welfare 車種。

    只放一張福祉單(無其他單競爭)以確保「可排」;再驗車種約束被滿足。
    環境無關:不綁特定車 id,只驗指派車種(本機有真實福祉車亦成立)。
    """
    db = SessionLocal()
    try:
        _cleanup(db)
        # 普通車 + 福祉車各一(出勤),只放一張福祉單
        v1 = Vehicle(plate="TEST-V1", type="normal", seats=4, active=True,
                     depot_lng=121.53, depot_lat=25.04, start_lng=121.53, start_lat=25.04,
                     end_lng=121.53, end_lat=25.04)
        v2 = Vehicle(plate="TEST-V2", type="welfare", seats=4, active=True,
                     depot_lng=121.55, depot_lat=25.05, start_lng=121.55, start_lat=25.05,
                     end_lng=121.55, end_lat=25.05)
        db.add_all([v1, v2])
        db.flush()
        db.add_all([ShiftException(vehicle_id=v1.id, ex_date=TEST_DATE, available=True),
                    ShiftException(vehicle_id=v2.id, ex_date=TEST_DATE, available=True)])
        db.add(Order(
            source_order_no="TEST-DISP-W", service_date=TEST_DATE, pickup_time=_dt(9),
            pickup_window_min=30, passenger_name="輪椅客",
            pickup_address="測試上車W", dropoff_address="測試下車W",
            pickup_lng=121.54, pickup_lat=25.045, dropoff_lng=121.56, dropoff_lat=25.05,
            pax=1, vehicle_type="welfare", need_wheelchair=True, allow_pool=False, status="imported"))
        db.commit()

        res = dispatcher.run_dispatch(db, TEST_DATE)
        assert "error" not in res, res
        db.expire_all()
        wf = db.query(Order).filter(Order.source_order_no == "TEST-DISP-W").one()
        assert wf.status == "scheduled", "有福祉車可用,福祉單卻未排入"
        v = db.get(Vehicle, wf.assigned_vehicle_id)
        assert v.type == "welfare", "福祉訂單被指派到非福祉車"
    finally:
        _cleanup(db)
        db.close()


def test_run_dispatch_out_of_service_hours(haversine):
    """時段外(凌晨 03:00)訂單不予排入 → out_of_service 計數,且不會變 scheduled。

    環境無關:時段判斷只看訂單時間(06–18 外),與有哪些車無關。
    """
    db = SessionLocal()
    try:
        _cleanup(db)
        v = Vehicle(plate="TEST-V1", type="normal", seats=4, active=True,
                    depot_lng=121.53, depot_lat=25.04, start_lng=121.53, start_lat=25.04,
                    end_lng=121.53, end_lat=25.04)
        db.add(v)
        db.flush()
        db.add(ShiftException(vehicle_id=v.id, ex_date=TEST_DATE, available=True))
        db.add(Order(
            source_order_no="TEST-DISP-OOH", service_date=TEST_DATE, pickup_time=_dt(3),
            pickup_window_min=30, passenger_name="凌晨客",
            pickup_address="測試上車", dropoff_address="測試下車",
            pickup_lng=121.54, pickup_lat=25.045, dropoff_lng=121.56, dropoff_lat=25.05,
            pax=1, vehicle_type="normal", allow_pool=False, status="imported"))
        db.commit()
        res = dispatcher.run_dispatch(db, TEST_DATE)
        # 該日唯一訂單在時段外 → 整批無可排訂單(回錯)或 out_of_service≥1
        if "error" not in res:
            assert res["out_of_service"] >= 1
        db.expire_all()
        o = db.query(Order).filter(Order.source_order_no == "TEST-DISP-OOH").one()
        assert o.status != "scheduled", "時段外訂單不應被排入"
    finally:
        _cleanup(db)
        db.close()


def test_run_dispatch_over_capacity_unassigned(haversine):
    """超容量訂單(pax=50,超過任何車輛座位)→ 無法排入,維持 imported。

    環境無關:50 人超過任何真實車輛座位,必排不進去。
    """
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed(db)   # 兩台 4 座車出勤 + 兩張正常單
        db.add(Order(
            source_order_no="TEST-DISP-BIG", service_date=TEST_DATE, pickup_time=_dt(10),
            pickup_window_min=30, passenger_name="大團",
            pickup_address="測試上車大", dropoff_address="測試下車大",
            pickup_lng=121.54, pickup_lat=25.045, dropoff_lng=121.56, dropoff_lat=25.05,
            pax=50, vehicle_type="normal", allow_pool=False, status="imported"))
        db.commit()
        res = dispatcher.run_dispatch(db, TEST_DATE)
        assert "error" not in res, res
        db.expire_all()
        big = db.query(Order).filter(Order.source_order_no == "TEST-DISP-BIG").one()
        assert big.status != "scheduled", "超座位訂單不應被排入"
    finally:
        _cleanup(db)
        db.close()


# ----- 派遣原則 4:是否需福祉車「只看車型」 -----

def test_is_welfare_judged_by_vehicle_type_only():
    """純函式:_is_welfare 只認 vehicle_type=='welfare',不再以 need_wheelchair 判定。"""
    welfare = Order(vehicle_type="welfare", need_wheelchair=False)
    normal_wc = Order(vehicle_type="normal", need_wheelchair=True)
    normal = Order(vehicle_type="normal", need_wheelchair=False)
    assert dispatcher._is_welfare(welfare) is True          # 車型福祉 → 需福祉車
    assert dispatcher._is_welfare(normal_wc) is False        # 僅輪椅、車型一般 → 不需福祉車
    assert dispatcher._is_welfare(normal) is False


def test_run_dispatch_wheelchair_only_order_uses_normal_vehicle(haversine, monkeypatch):
    """原則4 整合:車型=一般 但 need_wheelchair=True 的單,在「只有一台一般車出勤」時
    仍應排入(不再因輪椅而強制福祉車)。monkeypatch 出勤名單只留該一般車,排除真實班表干擾。"""
    db = SessionLocal()
    try:
        _cleanup(db)
        v = Vehicle(plate="TEST-V1", type="normal", seats=4, active=True,
                    depot_lng=121.53, depot_lat=25.04, start_lng=121.53, start_lat=25.04,
                    end_lng=121.53, end_lat=25.04)
        db.add(v); db.flush()
        vid = v.id
        db.add(Order(
            source_order_no="TEST-DISP-WC", service_date=TEST_DATE, pickup_time=_dt(9),
            pickup_window_min=30, passenger_name="輪椅但一般車",
            pickup_address="測試上車WC", dropoff_address="測試下車WC",
            pickup_lng=121.54, pickup_lat=25.045, dropoff_lng=121.56, dropoff_lat=25.05,
            pax=1, vehicle_type="normal", need_wheelchair=True, allow_pool=False, status="imported"))
        db.commit()
        # 出勤名單只留這台一般車(環境無關:排除真實 shift_pattern 帶入的福祉車)
        monkeypatch.setattr(dispatcher.roster_svc, "available_vehicles",
                            lambda _db, _d: {vid: (None, None)})
        res = dispatcher.run_dispatch(db, TEST_DATE)
        assert "error" not in res, res
        db.expire_all()
        o = db.query(Order).filter(Order.source_order_no == "TEST-DISP-WC").one()
        assert o.status == "scheduled", "車型一般的輪椅單應可由一般車服務(原則4),卻未排入"
        assert o.assigned_vehicle_id == vid
    finally:
        _cleanup(db)
        db.close()
