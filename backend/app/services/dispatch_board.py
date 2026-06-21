"""派遣看板資料 + 可行性(時間衝突)偵測。

提供前端拖放看板:某日各車的趟次(依時間)+ 未指派欄;每車標出時間衝突
(占用區間重疊),供人工微調時即時看到問題(如 14:20 與 14:30 撞車)。
"""
from __future__ import annotations

from datetime import date, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dispatch_history import DispatchHistory
from app.models.driver import Driver
from app.models.driver_vehicle_assignment import DriverVehicleAssignment
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import roster as roster_svc

TW = timezone(timedelta(hours=8))
_DEFAULT_DUR_MIN = 40   # 無 est 時的預設單趟占用(分)


def _hhmm(dt):
    return dt.astimezone(TW).strftime("%H:%M") if dt else None


def _mins(dt):
    if not dt:
        return None
    t = dt.astimezone(TW)
    return t.hour * 60 + t.minute


def board(db: Session, service_date: date) -> dict:
    # 已指派(scheduled/ongoing=即時派遣;done=歷史日實際派遣,讓 2025 等歷史日也看得到趟次)
    assigned = list(db.scalars(
        select(Order).where(
            Order.service_date == service_date,
            Order.status.in_(("scheduled", "ongoing", "done")),
            Order.assigned_vehicle_id.is_not(None),
        )
    ).all())
    # 未指派(待派,已編碼)
    unassigned = list(db.scalars(
        select(Order).where(
            Order.service_date == service_date,
            Order.status == "imported",
            Order.pickup_lng.is_not(None),
        ).order_by(Order.pickup_time)
    ).all())

    # est 時長(由人工歷史 source_order_no 帶入,fallback 預設)
    nos = [o.source_order_no for o in assigned if o.source_order_no]
    est = {}
    if nos:
        for n, m in db.execute(
            select(DispatchHistory.source_order_no, DispatchHistory.est_minutes)
            .where(DispatchHistory.source_order_no.in_(nos))
        ).all():
            if m:
                est[n] = m

    duty = roster_svc.available_vehicles(db, service_date)
    veh_ids = set(duty) | {o.assigned_vehicle_id for o in assigned}
    vmap = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(veh_ids))).all()} if veh_ids else {}

    # 車輛 → 駕駛(當日輪車指派優先,否則司機預設車)
    drv_by_veh: dict[int, str] = {}
    for d in db.scalars(select(Driver).where(Driver.vehicle_id.is_not(None))).all():
        drv_by_veh.setdefault(d.vehicle_id, d.name)
    for a in db.scalars(select(DriverVehicleAssignment).where(
            DriverVehicleAssignment.service_date == service_date)).all():
        dn = db.get(Driver, a.driver_id)
        if dn:
            drv_by_veh[a.vehicle_id] = dn.name

    by_veh: dict[int, list[Order]] = {}
    for o in assigned:
        by_veh.setdefault(o.assigned_vehicle_id, []).append(o)

    def trip(o):
        return {
            "order_id": o.id, "time": _hhmm(o.pickup_time),
            "eta": _hhmm(o.eta), "passenger": o.passenger_name,
            "pickup": o.pickup_address, "dropoff": o.dropoff_address,
            "pax": o.pax, "welfare": o.vehicle_type == "welfare" or o.need_wheelchair,
            "status": o.status,
        }

    vehicles = []
    for vid in sorted(veh_ids, key=lambda x: (vmap[x].home_fleet or "" if x in vmap else "", vmap[x].plate or "" if x in vmap else "")):
        v = vmap.get(vid)
        trips_o = sorted(by_veh.get(vid, []), key=lambda o: o.pickup_time or service_date)
        # 衝突偵測:占用區間 [pickup, pickup+dur] 重疊
        conflict_ids = set()
        spans = []
        for o in trips_o:
            st = _mins(o.pickup_time)
            if st is None:
                continue
            dur = est.get(o.source_order_no, _DEFAULT_DUR_MIN)
            spans.append((st, st + int(dur), o.id))
        spans.sort()
        for i in range(1, len(spans)):
            if spans[i][0] < spans[i - 1][1]:   # 起點早於前一趟結束 → 重疊
                conflict_ids.add(spans[i][2])
                conflict_ids.add(spans[i - 1][2])
        trips = []
        for o in trips_o:
            t = trip(o)
            t["conflict"] = o.id in conflict_ids
            trips.append(t)
        vehicles.append({
            "vehicle_id": vid,
            "plate": v.plate if v else f"#{vid}",
            "driver": drv_by_veh.get(vid),
            "fleet": v.home_fleet if v else None,
            "on_duty": vid in duty,
            "trip_count": len(trips),
            "conflicts": len(conflict_ids),
            "trips": trips,
        })
    return {
        "service_date": service_date.isoformat(),
        "vehicles": vehicles,
        "unassigned": [trip(o) for o in unassigned],
        "unassigned_count": len(unassigned),
    }
