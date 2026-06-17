"""人工 vs 自動(VROOM)對比引擎。

對某車行某日:取「已成行」訂單 + 人工當天實際用到的車 → 跑 VROOM(OSRM 矩陣)
→ 比較用車數 / 行駛 / 可行性。唯讀(不寫排班),結果存 dispatch_comparison。
"""
from __future__ import annotations

from datetime import date, time, timedelta, timezone

import numpy as np
import vroom
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.dispatch_comparison import DispatchComparison
from app.models.dispatch_history import DispatchHistory
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import matrix as matrix_svc

DELIVERY_OFFSET = 1_000_000
UNROUTABLE = 9_999_999
SERVED = "已轉至正式單"
TW = timezone(timedelta(hours=8))   # 台灣時區:上車時間以 +08 牆鐘換算當日秒數

# --- 司機工時 / 共乘 營運規則 ---
TRIP_SETUP = 1200          # 上車前 20 分(秒)
TRIP_TEARDOWN = 1200       # 下車後 20 分(秒)→ 每趟前後共 40 分工時
DAY_START = 6 * 3600       # 接送服務時段起 06:00
DAY_END = 18 * 3600        # 接送服務時段迄 18:00
MAX_WORK_SEC = 8 * 3600    # 每車每日工時上限 8h(VROOM 以行車+服務時間近似)
EXCL_CAP = 100             # 「不共乘」維度容量;未同意共乘者佔滿 → 獨佔整車


def _secs(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _secs_tw(dt) -> int:
    """上車 datetime 換算為台灣當日秒數(資料庫存 UTC,需轉 +08)。"""
    local = dt.astimezone(TW) if dt.tzinfo else dt
    return local.hour * 3600 + local.minute * 60 + local.second


def compare_day(db: Session, fleet: str, service_date: date, window_min: int = 30) -> dict | None:
    """回傳對比指標 dict;當日無成行單或無車則回 None。"""
    orders = list(db.scalars(
        select(Order).where(
            Order.fleet == fleet, Order.service_date == service_date,
            Order.status == "done",
            Order.pickup_lng.is_not(None), Order.dropoff_lng.is_not(None),
        ).order_by(Order.id)
    ).all())
    if not orders:
        return None

    plates = [p for (p,) in db.execute(
        select(DispatchHistory.plate.distinct()).where(
            DispatchHistory.fleet == fleet, DispatchHistory.service_date == service_date,
            DispatchHistory.status == SERVED, DispatchHistory.plate.like("R%"),
        )
    ).all() if p]
    vehicles = list(db.scalars(select(Vehicle).where(Vehicle.plate.in_(plates))).all()) if plates else []
    if not vehicles:
        return None

    # 點位 + 索引
    points: list[tuple[float, float]] = []
    index: dict[tuple[float, float], int] = {}

    def pt(lng, lat) -> int:
        k = (round(lng, 6), round(lat, 6))
        if k not in index:
            index[k] = len(points)
            points.append(k)
        return index[k]

    # 車輛出車起點 / 收車終點(start≠end);缺則退化到 depot
    def _first(*pairs):
        for lng, lat in pairs:
            if lng is not None and lat is not None:
                return (lng, lat)
        return None

    veh_se: dict[int, tuple[int, int]] = {}
    for v in vehicles:
        s = _first((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
        e = _first((v.end_lng, v.end_lat), (v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
        if s is not None:
            si = pt(*s)
            ei = pt(*e) if e is not None else si
            veh_se[v.id] = (si, ei)
    ord_pts = {o.id: (pt(o.pickup_lng, o.pickup_lat), pt(o.dropoff_lng, o.dropoff_lat)) for o in orders}

    m = matrix_svc.build_matrix(points)
    arr = np.array(
        [[int(round(c)) if c is not None else UNROUTABLE for c in row] for row in m["durations"]],
        dtype=np.uint32,
    )

    problem = vroom.Input()
    problem.set_durations_matrix("car", arr)
    for v in vehicles:
        # 彈性工時:不綁固定班別,僅受 06:00–18:00 服務時段 + 8h 工時上限約束
        # capacity = [座位, 不共乘維度];共乘規則用第二維度表達
        kw = dict(id=v.id, profile="car",
                  capacity=[max(1, v.seats or 1), EXCL_CAP],
                  skills={1} if v.type == "welfare" else set(),
                  time_window=vroom.TimeWindow(DAY_START, DAY_END),
                  max_travel_time=MAX_WORK_SEC)
        if v.id in veh_se:
            kw["start"], kw["end"] = veh_se[v.id]
        problem.add_vehicle(vroom.Vehicle(**kw))
    for o in orders:
        p_idx, d_idx = ord_pts[o.id]
        s = _secs_tw(o.pickup_time)
        welfare = o.vehicle_type == "welfare" or bool(o.need_wheelchair)
        # 共乘需同意:未同意者第二維度佔滿 EXCL_CAP → 與任何單都無法同車(獨佔)
        excl = 1 if o.allow_pool else EXCL_CAP
        problem.add_shipment(
            vroom.ShipmentStep(id=o.id, location=p_idx, default_service=TRIP_SETUP,
                               time_windows=[vroom.TimeWindow(s, s + window_min * 60)]),
            vroom.ShipmentStep(id=o.id + DELIVERY_OFFSET, location=d_idx, default_service=TRIP_TEARDOWN),
            amount=vroom.Amount([max(1, o.pax or 1), excl]),
            skills={1} if welfare else set(),
            priority=100,  # 人工當天已全數服務 → 強制 VROOM 盡量服務,再看需幾台車
        )

    sol = problem.solve(exploration_level=5, nb_threads=4)
    df = sol.routes
    vroom_vehicles = int(df[df["type"] == "pickup"]["vehicle_id"].nunique()) if len(df) else 0
    unassigned = int(sol.summary.unassigned)
    drive_sec = float(sol.summary.duration)

    human_vehicles = len(plates)
    hd = db.execute(
        select(func.coalesce(func.sum(DispatchHistory.distance_m), 0),
               func.coalesce(func.sum(DispatchHistory.est_minutes), 0))
        .where(DispatchHistory.fleet == fleet, DispatchHistory.service_date == service_date,
               DispatchHistory.status == SERVED)
    ).one()

    return {
        "fleet": fleet, "service_date": service_date, "window_min": window_min,
        "n_orders": len(orders),
        "human_vehicles": human_vehicles,
        "vroom_vehicles": vroom_vehicles,
        "vroom_unassigned": unassigned,
        "saved_vehicles": human_vehicles - vroom_vehicles,
        "human_distance_m": float(hd[0]), "human_minutes": float(hd[1]),
        "vroom_drive_sec": drive_sec,
    }


def run_batch(db: Session, window_min: int = 30, progress=None) -> dict:
    """對所有(車行×有成行單的日子)做對比,結果寫入 dispatch_comparison。"""
    db.query(DispatchComparison).delete()
    db.commit()

    combos = db.execute(
        select(Order.fleet, Order.service_date)
        .where(Order.status == "done")
        .group_by(Order.fleet, Order.service_date)
        .order_by(Order.fleet, Order.service_date)
    ).all()

    done = 0
    skipped = 0
    for fleet, sd in combos:
        try:
            r = compare_day(db, fleet, sd, window_min)
        except Exception:  # noqa: BLE001
            r = None
        if r is None:
            skipped += 1
            continue
        db.add(DispatchComparison(**r))
        done += 1
        if done % 25 == 0:
            db.commit()
            if progress:
                progress(done, len(combos))
    db.commit()
    return {"combos": len(combos), "compared": done, "skipped": skipped}


def sensitivity(db: Session, windows: list[int], fleet: str | None = None,
                sample_days: int = 20, progress=None) -> dict:
    """時間窗敏感度:在多個上車時間窗下,對同一組取樣日重跑 VROOM,
    呈現「放寬時間窗 → 省更多車 vs 未派趟次」的權衡(供報價/SLA 決策)。

    取樣自已有對比結果中最忙的 sample_days 天,確保各 window 比較基準一致。
    """
    q = select(DispatchComparison.fleet, DispatchComparison.service_date, DispatchComparison.n_orders)
    if fleet:
        q = q.where(DispatchComparison.fleet == fleet)
    combos = db.execute(q.order_by(DispatchComparison.n_orders.desc()).limit(sample_days)).all()
    if not combos:
        return {"fleet": fleet, "sample_days": 0, "windows": []}

    rows = []
    for i, w in enumerate(sorted(set(windows))):
        hv = vv = saved = unassigned = days = orders = 0
        for f, sd, _ in combos:
            try:
                r = compare_day(db, f, sd, w)
            except Exception:  # noqa: BLE001
                r = None
            if r is None:
                continue
            days += 1
            orders += r["n_orders"]
            hv += r["human_vehicles"]
            vv += r["vroom_vehicles"]
            saved += r["saved_vehicles"]
            unassigned += r["vroom_unassigned"]
        rows.append({
            "window_min": w, "days": days, "orders": orders,
            "human_vehicle_days": hv, "vroom_vehicle_days": vv,
            "saved_vehicle_days": saved, "vroom_unassigned": unassigned,
            "saved_pct": round(100.0 * saved / hv, 1) if hv else 0,
            "unassigned_pct": round(100.0 * unassigned / orders, 1) if orders else 0,
        })
        if progress:
            progress(i + 1, len(set(windows)))
    return {"fleet": fleet, "sample_days": len(combos), "windows": rows}
