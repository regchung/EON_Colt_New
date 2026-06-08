"""VROOM 自動排班:把某日訂單最佳化分配給車輛。

模型對照:
- 每張訂單   = VROOM shipment(pickup 上車 → delivery 下車)
- 福祉車需求 = skills {1}(訂單與福祉車都帶 1;福祉車能力為超集,可兼接一般單)
- 共乘座位   = amount [pax] + 車輛 capacity [seats]
- 預約時間   = pickup time_windows
- 班別       = 車輛 time_window
- 行車時間   = 自架 OSRM 矩陣(app.services.matrix)
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import vroom
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.route import RouteStop
from app.models.vehicle import Vehicle
from app.services import matrix as matrix_svc

DELIVERY_OFFSET = 1_000_000          # 用來區分 pickup/delivery 的 step id
PICKUP_SERVICE = 120                 # 上車作業秒數
DELIVERY_SERVICE = 120               # 下車作業秒數
UNROUTABLE = 9_999_999               # 矩陣中無法到達的填充值


def _secs_of_day(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _pickup_window(o: Order) -> tuple[int, int]:
    start = _secs_of_day(o.pickup_time.timetz())
    return start, start + (o.pickup_window_min or 0) * 60


def _is_welfare(o: Order) -> bool:
    return o.vehicle_type == "welfare" or bool(o.need_wheelchair)


def run_dispatch(db: Session, service_date: date) -> dict:
    # 1) 取當日可排訂單(已地理編碼)與可用車輛
    orders = list(
        db.scalars(
            select(Order)
            .where(Order.service_date == service_date)
            .where(Order.status.in_(("imported", "scheduled")))
            .where(Order.pickup_lng.is_not(None), Order.dropoff_lng.is_not(None))
            .order_by(Order.id)
        ).all()
    )
    vehicles = list(
        db.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.id)).all()
    )
    skipped = list(
        db.scalars(
            select(Order)
            .where(Order.service_date == service_date)
            .where(Order.status.in_(("imported", "scheduled")))
            .where((Order.pickup_lng.is_(None)) | (Order.dropoff_lng.is_(None)))
        ).all()
    )

    if not orders:
        return {"error": "該日沒有可排班的已編碼訂單", "skipped_no_coords": [o.id for o in skipped]}
    if not vehicles:
        return {"error": "沒有可用車輛(active)"}

    # 2) 收集座標點(去重)→ 索引
    points: list[tuple[float, float]] = []
    index: dict[tuple[float, float], int] = {}

    def pt_index(lng: float, lat: float) -> int:
        key = (round(lng, 6), round(lat, 6))
        if key not in index:
            index[key] = len(points)
            points.append(key)
        return index[key]

    veh_start = {}
    for v in vehicles:
        if v.depot_lng is not None and v.depot_lat is not None:
            veh_start[v.id] = pt_index(v.depot_lng, v.depot_lat)
    ord_pts = {}
    for o in orders:
        ord_pts[o.id] = (
            pt_index(o.pickup_lng, o.pickup_lat),
            pt_index(o.dropoff_lng, o.dropoff_lat),
        )

    # 3) 取 OSRM 行車時間矩陣
    m = matrix_svc.build_matrix(points)
    durations = m["durations"]
    arr = np.array(
        [[int(round(c)) if c is not None else UNROUTABLE for c in row] for row in durations],
        dtype=np.uint32,
    )

    # 4) 組 VROOM 問題
    problem = vroom.Input()
    problem.set_durations_matrix("car", arr)

    for v in vehicles:
        shift = (
            (_secs_of_day(v.shift_start), _secs_of_day(v.shift_end))
            if v.shift_start and v.shift_end
            else (0, 86399)
        )
        kwargs = dict(
            id=v.id,
            profile="car",
            capacity=[max(1, v.seats or 1)],
            skills={1} if v.type == "welfare" else set(),
            time_window=vroom.TimeWindow(shift[0], shift[1]),
        )
        if v.id in veh_start:
            kwargs["start"] = veh_start[v.id]
            kwargs["end"] = veh_start[v.id]
        problem.add_vehicle(vroom.Vehicle(**kwargs))

    for o in orders:
        p_idx, d_idx = ord_pts[o.id]
        pw_start, pw_end = _pickup_window(o)
        pickup = vroom.ShipmentStep(
            id=o.id, location=p_idx, default_service=PICKUP_SERVICE,
            time_windows=[vroom.TimeWindow(pw_start, pw_end)],
        )
        delivery = vroom.ShipmentStep(
            id=o.id + DELIVERY_OFFSET, location=d_idx, default_service=DELIVERY_SERVICE,
        )
        problem.add_shipment(
            pickup, delivery,
            amount=vroom.Amount([max(1, o.pax or 1)]),
            skills={1} if _is_welfare(o) else set(),
            priority=50,
        )

    sol = problem.solve(exploration_level=5, nb_threads=4)

    # 5) 寫回結果(先清空當日待排訂單的舊指派,確保可重複排班)
    for o in orders:
        o.assigned_vehicle_id = None
        o.dispatch_seq = None
        o.eta = None
        o.status = "imported"

    by_id = {o.id: o for o in orders}
    midnight = datetime.combine(service_date, time(0), tzinfo=timezone.utc)
    routes_report: dict[int, list[dict]] = {}
    pickup_seq: dict[int, int] = {}     # 訂單派遣順序(只計上車)
    stop_seq: dict[int, int] = {}       # 路線停靠順序(含 start/end/上下車)

    # 清掉當日舊路線
    db.query(RouteStop).filter(RouteStop.service_date == service_date).delete()

    df = sol.routes
    for _, step in df.iterrows():
        vid = int(step["vehicle_id"])
        stype = step["type"]
        routes_report.setdefault(vid, [])
        sid = step["id"]
        arrival = int(step["arrival"])
        eta_dt = midnight + timedelta(seconds=arrival)
        arr_hhmm = eta_dt.strftime("%H:%M")
        loc = step["location_index"]
        lng = lat = None
        if loc == loc and int(loc) < len(points):  # not NaN
            lng, lat = points[int(loc)]

        kind, oid, addr = stype, None, None
        if stype == "pickup" and sid == sid:
            oid = int(sid)
            o = by_id.get(oid)
            if o:
                seq = pickup_seq.get(vid, 0) + 1
                pickup_seq[vid] = seq
                o.assigned_vehicle_id = vid
                o.dispatch_seq = seq
                o.eta = eta_dt
                o.status = "scheduled"
                addr = o.pickup_address
                routes_report[vid].append(
                    {"seq": seq, "order_id": oid, "type": "上車", "eta": arr_hhmm, "addr": addr}
                )
        elif stype == "delivery" and sid == sid:
            oid = int(sid) - DELIVERY_OFFSET
            o = by_id.get(oid)
            if o:
                addr = o.dropoff_address
                routes_report[vid].append(
                    {"order_id": oid, "type": "下車", "eta": arr_hhmm, "addr": addr}
                )

        sseq = stop_seq.get(vid, 0) + 1
        stop_seq[vid] = sseq
        db.add(RouteStop(
            service_date=service_date, vehicle_id=vid, seq=sseq, kind=kind,
            order_id=oid, lng=lng, lat=lat, eta=eta_dt, address=addr,
        ))

    db.commit()

    assigned_ids = {o.id for o in orders if o.assigned_vehicle_id is not None}
    unassigned = [o.id for o in orders if o.id not in assigned_ids]

    return {
        "service_date": service_date.isoformat(),
        "provider": m["provider"],
        "vehicles_used": len(routes_report),
        "orders_total": len(orders),
        "assigned": len(assigned_ids),
        "unassigned": unassigned,
        "skipped_no_coords": [o.id for o in skipped],
        "total_duration_sec": int(sol.summary.duration),
        "routes": routes_report,
    }
