"""共乘推薦:雙跑 VROOM(禁止 / 允許共乘)→ 找出「值得徵詢同意」的配對 + 量化效益。

概念:
- 跑兩次同一天的排班:A=維持現況(僅已同意者可共乘)、B=放寬(全部允許共乘)。
- B 比 A 少用的車 = 共乘可省的車;B 中「同車且同時在車上」的訂單 = 該徵詢同意的名單。
- 每組附帶繞路分鐘(長照舒適度護欄),繞太久的組別不推薦。
唯讀,不寫任何資料。
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import vroom
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dispatch_history import DispatchHistory
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import matrix as matrix_svc
from app.services.comparison import (
    DAY_END, DAY_START, DELIVERY_OFFSET, EXCL_CAP, MAX_WORK_SEC, SERVED,
    TRIP_SETUP, TRIP_TEARDOWN, UNROUTABLE, _secs_tw,
)


def _build(db: Session, fleet: str, service_date: date):
    """取當日成行單 + 人工實際用車 + OSRM 矩陣 + 點位索引。"""
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

    points: list[tuple[float, float]] = []
    index: dict[tuple[float, float], int] = {}

    def pt(lng, lat) -> int:
        k = (round(lng, 6), round(lat, 6))
        if k not in index:
            index[k] = len(points)
            points.append(k)
        return index[k]

    def first(*pairs):
        for lng, lat in pairs:
            if lng is not None and lat is not None:
                return (lng, lat)
        return None

    veh_se = {}
    for v in vehicles:
        s = first((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
        e = first((v.end_lng, v.end_lat), (v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
        if s is not None:
            veh_se[v.id] = (pt(*s), pt(*e) if e is not None else pt(*s))
    ord_pts = {o.id: (pt(o.pickup_lng, o.pickup_lat), pt(o.dropoff_lng, o.dropoff_lat)) for o in orders}

    m = matrix_svc.build_matrix(points)
    arr = np.array(
        [[int(round(c)) if c is not None else UNROUTABLE for c in row] for row in m["durations"]],
        dtype=np.uint32,
    )
    return orders, vehicles, arr, ord_pts, veh_se


def _solve(orders, vehicles, arr, ord_pts, veh_se, window_min: int, allow_all: bool):
    problem = vroom.Input()
    problem.set_durations_matrix("car", arr)
    for v in vehicles:
        kw = dict(id=v.id, profile="car", capacity=[max(1, v.seats or 1), EXCL_CAP],
                  skills={1} if v.type == "welfare" else set(),
                  time_window=vroom.TimeWindow(DAY_START, DAY_END), max_travel_time=MAX_WORK_SEC)
        if v.id in veh_se:
            kw["start"], kw["end"] = veh_se[v.id]
        problem.add_vehicle(vroom.Vehicle(**kw))
    for o in orders:
        pi, di = ord_pts[o.id]
        s = _secs_tw(o.pickup_time)
        welfare = o.vehicle_type == "welfare" or bool(o.need_wheelchair)
        excl = 1 if (allow_all or o.allow_pool) else EXCL_CAP
        problem.add_shipment(
            vroom.ShipmentStep(id=o.id, location=pi, default_service=TRIP_SETUP,
                               time_windows=[vroom.TimeWindow(s, s + window_min * 60)]),
            vroom.ShipmentStep(id=o.id + DELIVERY_OFFSET, location=di, default_service=TRIP_TEARDOWN),
            amount=vroom.Amount([max(1, o.pax or 1), excl]),
            skills={1} if welfare else set(), priority=100,
        )
    return problem.solve(exploration_level=5, nb_threads=4)


def _vehicles_used(sol) -> int:
    df = sol.routes
    return int(df[df["type"] == "pickup"]["vehicle_id"].nunique()) if len(df) else 0


def _onboard_groups(sol, orders, arr, ord_pts) -> list[dict]:
    """從『允許共乘』解中,找出同車且時間重疊(同時在車上)的訂單群組(size≥2)。"""
    by = {o.id: o for o in orders}
    rec: dict[int, dict] = {}
    for _, st in sol.routes.iterrows():
        sid = st["id"]
        if pd.isna(sid):
            continue
        sid = int(sid)
        if st["type"] == "pickup":
            rec.setdefault(sid, {})["veh"] = int(st["vehicle_id"])
            rec[sid]["pu"] = int(st["arrival"])
        elif st["type"] == "delivery":
            rec.setdefault(sid - DELIVERY_OFFSET, {})["do"] = int(st["arrival"])

    # 依車輛分組,找區間重疊的連通分量
    veh_orders: dict[int, list[int]] = {}
    for oid, r in rec.items():
        if "veh" in r and "pu" in r and "do" in r:
            veh_orders.setdefault(r["veh"], []).append(oid)

    groups: list[dict] = []
    for veh, oids in veh_orders.items():
        oids.sort(key=lambda i: rec[i]["pu"])
        used = set()
        for i, a in enumerate(oids):
            if a in used:
                continue
            comp = [a]
            hi = rec[a]["do"]
            for b in oids[i + 1:]:
                if rec[b]["pu"] < hi:  # 與目前群組時間重疊 → 同時在車上
                    comp.append(b)
                    hi = max(hi, rec[b]["do"])
            if len(comp) >= 2:
                used.update(comp)
                members = []
                for oid in comp:
                    o = by[oid]
                    p_idx, d_idx = ord_pts[oid]
                    direct = int(arr[p_idx][d_idx])
                    onboard = rec[oid]["do"] - rec[oid]["pu"] - TRIP_SETUP - TRIP_TEARDOWN
                    detour = max(0, onboard - direct)
                    members.append({
                        "order_id": oid,
                        "passenger": o.passenger_name,
                        "pickup": o.pickup_address, "dropoff": o.dropoff_address,
                        "pax": o.pax, "welfare": o.vehicle_type == "welfare" or bool(o.need_wheelchair),
                        "already_consented": bool(o.allow_pool),
                        "detour_min": round(detour / 60, 1),
                    })
                groups.append({
                    "vehicle_id": veh,
                    "size": len(comp),
                    "max_detour_min": round(max(mm["detour_min"] for mm in members), 1),
                    "members": members,
                })
    return groups


def suggest_day(db: Session, fleet: str, service_date: date,
                window_min: int = 30, max_detour_min: float = 15.0) -> dict | None:
    """單日共乘推薦:回傳省車數 + 建議徵詢同意的群組(已過濾繞路過大者)。"""
    built = _build(db, fleet, service_date)
    if built is None:
        return None
    orders, vehicles, arr, ord_pts, veh_se = built

    sol_now = _solve(orders, vehicles, arr, ord_pts, veh_se, window_min, allow_all=False)
    sol_pool = _solve(orders, vehicles, arr, ord_pts, veh_se, window_min, allow_all=True)
    v_now = _vehicles_used(sol_now)
    v_pool = _vehicles_used(sol_pool)

    groups = _onboard_groups(sol_pool, orders, arr, ord_pts)
    comfortable = [g for g in groups if g["max_detour_min"] <= max_detour_min]
    # 只需徵詢「尚未同意」的成員所在群組
    to_ask = [g for g in comfortable if any(not m["already_consented"] for m in g["members"])]

    return {
        "fleet": fleet, "service_date": service_date.isoformat(),
        "n_orders": len(orders),
        "vehicles_now": v_now,           # 現況(僅已同意者共乘)
        "vehicles_if_pooled": v_pool,    # 若推薦組同意後
        "vehicles_saved": v_now - v_pool,
        "groups_total": len(groups),
        "groups_comfortable": len(comfortable),
        "groups_to_ask": len(to_ask),
        "max_detour_min": max_detour_min,
        "suggestions": to_ask,
    }


def project_batch(db: Session, window_min: int = 30, progress=None) -> dict:
    """全車行×日:統計『現況共乘』vs『推薦組全同意』的車日,量化共乘名單的整體效益。"""
    combos = db.execute(
        select(Order.fleet, Order.service_date)
        .where(Order.status == "done")
        .group_by(Order.fleet, Order.service_date)
        .order_by(Order.fleet, Order.service_date)
    ).all()

    agg = {"days": 0, "v_now": 0, "v_pool": 0, "ask_groups": 0, "ask_orders": 0}
    by_fleet: dict[str, dict] = {}
    done = 0
    for fleet, sd in combos:
        try:
            r = suggest_day(db, fleet, sd, window_min)
        except Exception:  # noqa: BLE001
            r = None
        if r is None:
            continue
        f = by_fleet.setdefault(fleet, {"days": 0, "v_now": 0, "v_pool": 0, "ask_groups": 0})
        agg["days"] += 1
        agg["v_now"] += r["vehicles_now"]
        agg["v_pool"] += r["vehicles_if_pooled"]
        agg["ask_groups"] += r["groups_to_ask"]
        agg["ask_orders"] += sum(len(g["members"]) for g in r["suggestions"])
        f["days"] += 1
        f["v_now"] += r["vehicles_now"]
        f["v_pool"] += r["vehicles_if_pooled"]
        f["ask_groups"] += r["groups_to_ask"]
        done += 1
        if progress and done % 25 == 0:
            progress(done, len(combos))

    def pct(now, pool):
        return round(100 * (now - pool) / now, 1) if now else 0

    agg["extra_saved_pct_vs_now"] = pct(agg["v_now"], agg["v_pool"])
    for f in by_fleet.values():
        f["extra_saved_pct_vs_now"] = pct(f["v_now"], f["v_pool"])
    return {"group": agg, "by_fleet": by_fleet}


def project_and_store(db: Session, window_min: int = 30, progress=None) -> dict:
    """跑投影並寫入 pool_projection(每車行一列),供報表/前端快速讀取。"""
    from app.models.pool_projection import PoolProjection

    res = project_batch(db, window_min, progress)
    db.query(PoolProjection).delete()
    for fleet, s in res["by_fleet"].items():
        db.add(PoolProjection(
            fleet=fleet, window_min=window_min, days=s["days"],
            v_now=s["v_now"], v_pool=s["v_pool"],
            saved_vehicles=s["v_now"] - s["v_pool"], ask_groups=s["ask_groups"],
        ))
    db.commit()
    return res
