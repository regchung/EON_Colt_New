"""comparison.compare_day_by_vehicle 整合測試:逐車並排對比(離線 VROOM)。

設 MATRIX_PROVIDER=haversine 免 OSRM 跑完整求解。自建小場景:
2 台車(車牌 R 開頭)、3 筆成行單 + 對應人工派遣紀錄(dispatch_history),
驗證回傳結構、車牌左右對映、里程/工時同方法學(含距離),以及 totals。
測試資料以 RTSTCMP / TEST-CMP 前綴 + 遠期日期標記,finally 徹底清理。
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.dispatch_history import DispatchHistory
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import comparison

TW = timezone(timedelta(hours=8))
CMP_DATE = date(2099, 2, 9)
FLEET = "RTSTCMP"


def _dt(h, m=0):
    return datetime(2099, 2, 9, h, m, tzinfo=TW)


def _cleanup(db):
    db.execute(delete(DispatchHistory).where(DispatchHistory.source_order_no.like("TEST-CMP-%")))
    db.execute(delete(Order).where(Order.source_order_no.like("TEST-CMP-%")))
    db.execute(delete(Vehicle).where(Vehicle.plate.like("RTSTCMP%")))
    db.commit()


def _seed(db):
    va = Vehicle(plate="RTSTCMPA", type="normal", seats=4, active=True,
                 start_lng=121.53, start_lat=25.04, end_lng=121.53, end_lat=25.04)
    vb = Vehicle(plate="RTSTCMPB", type="normal", seats=4, active=True,
                 start_lng=121.55, start_lat=25.05, end_lng=121.55, end_lat=25.05)
    db.add_all([va, vb])
    db.flush()
    # 3 筆成行單(座標相近,VROOM 應可併到較少車)
    trips = [
        (121.540, 25.045, 121.560, 25.050),
        (121.545, 25.046, 121.558, 25.049),
        (121.520, 25.030, 121.550, 25.048),
    ]
    # 人工:A 派趟 0、1;B 派趟 2
    plates = ["RTSTCMPA", "RTSTCMPA", "RTSTCMPB"]
    for i, (plng, plat, dlng, dlat) in enumerate(trips):
        no = f"TEST-CMP-{i}"
        db.add(Order(
            source_order_no=no, fleet=FLEET, service_date=CMP_DATE, pickup_time=_dt(8 + i),
            pickup_window_min=30, passenger_name=f"乘客{i}",
            pickup_address=f"上車{i}", dropoff_address=f"下車{i}",
            pickup_lng=plng, pickup_lat=plat, dropoff_lng=dlng, dropoff_lat=dlat,
            pax=1, vehicle_type="normal", allow_pool=True, status="done",
        ))
        db.add(DispatchHistory(
            source_order_no=no, fleet=FLEET, service_date=CMP_DATE, pickup_time=_dt(8 + i),
            plate=plates[i], driver_name=f"司機{i}", status=comparison.SERVED,
            pickup_address=f"上車{i}", dropoff_address=f"下車{i}",
            pickup_lng=plng, pickup_lat=plat, dropoff_lng=dlng, dropoff_lat=dlat,
            distance_m=3000.0 + i * 500, est_minutes=12.0 + i,
        ))
    db.commit()


@pytest.fixture
def haversine(monkeypatch):
    monkeypatch.setattr(settings, "MATRIX_PROVIDER", "haversine")


def test_max_ride_upper_caps_long_rides():
    """最長乘車時間上限:不可路由不設限、短程取下限、一般取倍率+緩衝。"""
    up = comparison._max_ride_upper(3000, 36600)
    assert up == 36600 + max(comparison.MIN_MAX_RIDE_SEC,
                             int(3000 * comparison.RIDE_FACTOR) + comparison.RIDE_GRACE_SEC)
    # 短程(60s)→ 取下限
    assert comparison._max_ride_upper(60, 36600) == 36600 + comparison.MIN_MAX_RIDE_SEC
    # 不可路由 → None(不設限)
    assert comparison._max_ride_upper(comparison.UNROUTABLE, 36600) is None
    # 乘車上限部分(扣掉上車窗末)應有界、遠小於「載一整天」(50 分直達 → 約 2h)
    assert (comparison._max_ride_upper(3000, 36600) - 36600) < 4 * 3600


class _O:
    def __init__(self, vt="normal", plng=121.5, plat=25.05, dlng=121.52, dlat=25.06):
        self.vehicle_type = vt
        self.pickup_lng, self.pickup_lat = plng, plat
        self.dropoff_lng, self.dropoff_lat = dlng, dlat


def test_classify_unassigned_actionable_codes():
    C = comparison
    centroid = (121.51, 25.05)        # 雙北營運區
    day = 9 * 3600                    # 09:00 服務時段內
    # 1) 服務時段外
    assert C._classify_unassigned(_O(), 5 * 3600, 600, True, centroid, True)[0] == "out_of_hours"
    # 2) 需福祉、無福祉車
    assert C._classify_unassigned(_O(vt="welfare"), day, 600, False, centroid, True)[0] == "no_welfare"
    # 3) 座標離營運區過遠(編到台中)→ suspect_geocode
    bad = _O(plng=120.69, plat=24.13)
    assert C._classify_unassigned(bad, day, 600, True, centroid, True)[0] == "suspect_geocode"
    # 4) 區內 + 全車隊滿載 → fleet_saturated
    assert C._classify_unassigned(_O(), day, 600, True, centroid, True)[0] == "fleet_saturated"
    # 5) 區內 + 仍有閒置 → solver_margin
    assert C._classify_unassigned(_O(), day, 600, True, centroid, False)[0] == "solver_margin"


def test_km_haversine_roughly_correct():
    # 台北↔台中 約 130–160 km
    assert 120 < comparison._km(121.51, 25.05, 120.68, 24.14) < 180


def test_dispatcher_max_ride_upper_factor_zero_disables():
    from app.services import dispatcher as D
    assert D._max_ride_upper(3000, 36600, 0, 1800) is None        # 倍率 0 = 不限
    assert D._max_ride_upper(D.UNROUTABLE, 36600, 1.8, 1800) is None
    up = D._max_ride_upper(3000, 36600, 1.8, 1800)
    assert up == 36600 + max(D.MIN_MAX_RIDE_SEC, int(3000 * 1.8) + 1800)


def test_compare_day_by_vehicle_structure(haversine):
    db = SessionLocal()
    try:
        _cleanup(db)
        _seed(db)
        r = comparison.compare_day_by_vehicle(db, FLEET, CMP_DATE, window_min=30)
        assert r is not None
        assert r["n_orders"] == 3
        assert r["distance_available"] is True   # haversine 提供距離

        # 兩台人工用過的車都應出現,且以車牌對映
        plates = {v["plate"] for v in r["vehicles"]}
        assert {"RTSTCMPA", "RTSTCMPB"} <= plates

        # 每車結構完整:human / auto 皆含里程與工時(同方法學)
        for v in r["vehicles"]:
            for side in ("human", "auto"):
                assert set(["n", "distance_km", "drive_min", "work_min", "orders"]) <= set(v[side])
            # 人工另含來源檔記載里程/分鐘(參考)
            assert "loaded_km" in v["human"] and "rec_min" in v["human"]
            # 自動含真實停靠序(交錯上/下車 + 到點 + 在車人數)
            assert "stops" in v["auto"]
            for st in v["auto"]["stops"]:
                assert st["kind"] in ("上車", "下車")
                assert ":" in st["eta"] and "onboard" in st
            # 在車人數不應為負(上/下車配對正確)
            assert all(st["onboard"] >= 0 for st in v["auto"]["stops"])

        # 人工用 2 台;自動最佳化後不應更多(理應 <= 2)
        assert r["totals"]["human"]["vehicles"] == 2
        assert 1 <= r["totals"]["auto"]["vehicles"] <= 2

        # 全部 3 趟都應被自動排入(座標相近、時間寬鬆)
        auto_trips = sum(v["auto"]["n"] for v in r["vehicles"])
        assert auto_trips + len(r["auto_unassigned"]) == 3

        # 工時為正(含每趟前後 40 分作業 + 行駛)
        assert r["totals"]["human"]["work_min"] > 0
        assert r["totals"]["auto"]["work_min"] > 0
    finally:
        _cleanup(db)
        db.close()
