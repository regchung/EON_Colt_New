"""人工 vs 自動(VROOM)對比引擎。

對某車行某日:取「已成行」訂單 + 人工當天實際用到的車 → 跑 VROOM(OSRM 矩陣)
→ 比較用車數 / 行駛 / 可行性。唯讀(不寫排班),結果存 dispatch_comparison。
"""
from __future__ import annotations

from datetime import date, time

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


def _secs(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


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

    veh_start = {}
    for v in vehicles:
        if v.depot_lng is not None and v.depot_lat is not None:
            veh_start[v.id] = pt(v.depot_lng, v.depot_lat)
    ord_pts = {o.id: (pt(o.pickup_lng, o.pickup_lat), pt(o.dropoff_lng, o.dropoff_lat)) for o in orders}

    m = matrix_svc.build_matrix(points)
    arr = np.array(
        [[int(round(c)) if c is not None else UNROUTABLE for c in row] for row in m["durations"]],
        dtype=np.uint32,
    )

    problem = vroom.Input()
    problem.set_durations_matrix("car", arr)
    for v in vehicles:
        kw = dict(id=v.id, profile="car", capacity=[max(1, v.seats or 1)],
                  skills={1} if v.type == "welfare" else set(),
                  time_window=vroom.TimeWindow(0, 86399))
        if v.id in veh_start:
            kw["start"] = veh_start[v.id]
            kw["end"] = veh_start[v.id]
        problem.add_vehicle(vroom.Vehicle(**kw))
    for o in orders:
        p_idx, d_idx = ord_pts[o.id]
        s = _secs(o.pickup_time.timetz())
        welfare = o.vehicle_type == "welfare" or bool(o.need_wheelchair)
        problem.add_shipment(
            vroom.ShipmentStep(id=o.id, location=p_idx, default_service=120,
                               time_windows=[vroom.TimeWindow(s, s + window_min * 60)]),
            vroom.ShipmentStep(id=o.id + DELIVERY_OFFSET, location=d_idx, default_service=120),
            amount=vroom.Amount([max(1, o.pax or 1)]),
            skills={1} if welfare else set(),
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
