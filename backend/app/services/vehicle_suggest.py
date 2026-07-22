"""單筆訂單 → 最佳車輛建議(人工排班用)。

以真實 OSRM 行車時間估算「把這張單插進每台候選車現有路線的增加車程」,
搭配可行性檢查(車型/座位/服務時段/出勤/時間衝突),排名 Top-N。
本車行(同區)優先,可切換 fleet_scope 到他隊/全公司(對應自動派遣的跨車行支援)。

刻意為輕量插入啟發式(非重跑 VROOM):在人工微調的互動情境下要「即時、可解釋」,
給行控「該拖去哪台車 / 一鍵採用」的依據即可;精確全域最佳化仍由自動派遣負責。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.driver import Driver
from app.models.driver_vehicle_assignment import DriverVehicleAssignment
from app.models.vehicle import Vehicle
from app.services import dispatcher
from app.services import matrix as matrix_svc
from app.services import roster as roster_svc
from app.services import settings as settings_svc

TW = timezone(timedelta(hours=8))
_DEFAULT_DUR_MIN = 40   # 無 est 時單趟占用估算(與看板衝突偵測一致)
UNROUTABLE = 10 ** 8


def _mins(dt) -> int | None:
    if not dt:
        return None
    t = dt.astimezone(TW)
    return t.hour * 60 + t.minute


def _driver_by_veh(db: Session, service_date: date) -> dict[int, str]:
    out: dict[int, str] = {}
    for d in db.scalars(select(Driver).where(Driver.vehicle_id.is_not(None))).all():
        out.setdefault(d.vehicle_id, d.name)
    for a in db.scalars(select(DriverVehicleAssignment).where(
            DriverVehicleAssignment.service_date == service_date)).all():
        dn = db.get(Driver, a.driver_id)
        if dn:
            out[a.vehicle_id] = dn.name
    return out


def _candidate_vehicle_ids(db: Session, service_date: date) -> dict[int, tuple]:
    """當天可派候選車(有司機、未停派、出勤);沿用自動派遣的過濾原則。"""
    duty = roster_svc.available_vehicles(db, service_date)
    if not duty:   # 未建班表 → 全 active 車(仍受停派/司機過濾)
        duty = {vid: (None, None) for (vid,) in db.execute(
            select(Vehicle.id).where(Vehicle.active.is_(True))).all()}
    susp = {vid for (vid,) in db.execute(
        select(Vehicle.id).where(Vehicle.suspended.is_(True))).all()}
    driver_veh = dispatcher._vehicles_with_driver(db, service_date)
    return {vid: w for vid, w in duty.items()
            if vid not in susp and (not driver_veh or vid in driver_veh)}


def _in_scope(v: Vehicle, order: Order, fleet_scope: str | None) -> bool:
    # 單一車行（大豐），所有車輛皆在範圍內
    return True


def suggest_for_order(db: Session, order: Order, service_date: date,
                      top_n: int = 6, fleet_scope: str | None = "own") -> dict:
    """回傳該訂單的車輛建議:排名 + 每台增加車程(分)+ 可行性/理由。"""
    if order.pickup_lng is None or order.dropoff_lng is None:
        return {"order_id": order.id, "error": "此訂單尚未地理編碼,無法建議車輛。",
                "candidates": [], "recommended": None}

    prm = settings_svc.dispatch_params(db)
    day_start, day_end = prm["day_start_sec"], prm["day_end_sec"]
    duty = _candidate_vehicle_ids(db, service_date)
    vehicles = [v for v in db.scalars(
        select(Vehicle).where(Vehicle.id.in_(list(duty) or [-1]), Vehicle.active.is_(True))).all()
        if _in_scope(v, order, fleet_scope)]

    # 當日已指派(排班中/進行中)→ 每車現有停靠點(依時間)
    assigned = list(db.scalars(select(Order).where(
        Order.service_date == service_date,
        Order.assigned_vehicle_id.is_not(None),
        Order.status.in_(("scheduled", "ongoing")),
        Order.pickup_lng.is_not(None),
    )).all())
    by_veh: dict[int, list[Order]] = defaultdict(list)
    for o in assigned:
        by_veh[o.assigned_vehicle_id].append(o)

    # 收集所有座標點 → 索引(單一矩陣)
    points: list[tuple[float, float]] = []
    index: dict[tuple[float, float], int] = {}

    def pt(lng, lat) -> int:
        key = (round(lng, 6), round(lat, 6))
        if key not in index:
            index[key] = len(points)
            points.append(key)
        return index[key]

    np_i = pt(order.pickup_lng, order.pickup_lat)   # 新單上車
    nd_i = pt(order.dropoff_lng, order.dropoff_lat)  # 新單下車
    veh_start: dict[int, int] = {}
    veh_stops: dict[int, list[tuple[int, int]]] = {}   # vid -> [(time_min, point_idx)] 依時間
    for v in vehicles:
        s = dispatcher._first_coord((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
        if s is not None:
            veh_start[v.id] = pt(*s)
        stops: list[tuple[int, int]] = []
        for o in sorted(by_veh.get(v.id, []),
                        key=lambda x: (x.dispatch_seq or 0, x.pickup_time or service_date)):
            tmin = _mins(o.eta) or _mins(o.pickup_time) or 0
            stops.append((tmin, pt(o.pickup_lng, o.pickup_lat)))
            stops.append((tmin, pt(o.dropoff_lng, o.dropoff_lat)))
        veh_stops[v.id] = stops

    m = matrix_svc.build_matrix(points)
    dur = m["durations"]

    def d(a: int, b: int) -> float:
        c = dur[a][b]
        return UNROUTABLE if c is None else c

    direct = d(np_i, nd_i)   # 新單直達車程
    new_pw = _mins(order.pickup_time)
    new_welfare = dispatcher._is_welfare(order)
    pax = order.pax or 1

    cands = []
    for v in vehicles:
        stops = veh_stops[v.id]
        start_i = veh_start.get(v.id, np_i)
        # 最佳插入位置的「增加車程」(pickup+dropoff 連續插入)
        path = [start_i] + [p for (_t, p) in stops]
        if len(path) == 1:
            added = d(start_i, np_i) + direct   # 空車:起點→上車→下車
        else:
            best = None
            for i in range(len(path) - 1):
                a, b = path[i], path[i + 1]
                delta = d(a, np_i) + direct + d(nd_i, b) - d(a, b)
                if best is None or delta < best:
                    best = delta
            # 也可接在最後一站之後
            tail = d(path[-1], np_i) + direct
            added = min(best, tail) if best is not None else tail
        added_min = round(added / 60)
        pooled = len(stops) > 0

        # 可行性檢查
        reasons = []
        if new_welfare and v.type != "welfare":
            reasons.append("需福祉車")
        if pax > (v.seats or 1):
            reasons.append("座位不足")
        if new_pw is not None and (new_pw * 60 < day_start or new_pw * 60 > day_end):
            reasons.append("服務時段外")
        # 時間衝突:新單上車時間落在既有停靠 ±(單趟占用/2) 內(粗估,提示用)
        conflict = False
        if new_pw is not None:
            half = _DEFAULT_DUR_MIN // 2
            for (tmin, _p) in stops:
                if abs(tmin - new_pw) < half:
                    conflict = True
                    break
        if added >= UNROUTABLE / 10:
            reasons.append("無法路由")

        feasible = not reasons
        cands.append({
            "vehicle_id": v.id,
            "plate": v.plate or f"#{v.id}",
            "fleet": v.home_fleet,
            "is_own": True,   # 單一車行，所有車皆為本車行
            "is_support": False,
            "type": v.type,
            "trip_count": len(by_veh.get(v.id, [])),
            "added_min": added_min,
            "pooled": pooled,
            "conflict": conflict,
            "feasible": feasible,
            "reason": "、".join(reasons),
        })

    # 排序:可行 → 無衝突 → 增加車程少 → 現有趟少(平衡)
    cands.sort(key=lambda c: (
        not c["feasible"], c["conflict"], c["added_min"], c["trip_count"]
    ))
    top = cands[:top_n]
    feasible_list = [c for c in top if c["feasible"]]
    recommended = feasible_list[0] if feasible_list else (top[0] if top else None)

    # 補司機名(只補 Top-N)
    drv = _driver_by_veh(db, service_date)
    for c in top:
        c["driver"] = drv.get(c["vehicle_id"])

    return {
        "order_id": order.id,
        "order_fleet": order.fleet,
        "fleet_scope": fleet_scope,
        "welfare": new_welfare,
        "direct_min": round(direct / 60) if direct < UNROUTABLE / 10 else None,
        "candidate_count": len(cands),
        "candidates": top,
        "recommended": recommended,
    }
