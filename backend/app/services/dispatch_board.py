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


def board(db: Session, service_date: date, source: str = "human") -> dict:
    """source=human(orders 當前指派,可拖放微調)| auto(自動派遣落地,唯讀檢視)。"""
    if source == "auto":
        return _board_auto(db, service_date)
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
            "status": o.status, "fleet": o.fleet,
            "support_fleet": o.support_fleet,   # 跨車行支援留痕(他隊車服務時 ≠ fleet)
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


def _board_auto(db: Session, service_date: date) -> dict:
    """自動派遣看板(唯讀):趟次來自 auto_dispatch_stop 的 pickup 列,未派來自 unassigned_record。"""
    from app.models.auto_dispatch_stop import AutoDispatchStop
    from app.models.unassigned_record import UnassignedRecord

    allstops = list(db.scalars(select(AutoDispatchStop).where(
        AutoDispatchStop.service_date == service_date).order_by(
        AutoDispatchStop.vehicle_id, AutoDispatchStop.seq)).all())
    stops = [s for s in allstops if s.kind == "pickup"]   # 趟次以上車列為準
    # 真實下車時刻:(車, 訂單) → 下車 ETA 分鐘;用於「真實佔用時段」衝突判定(非固定 40 分)
    drop_min = {(s.vehicle_id, s.order_id): _mins(s.eta)
                for s in allstops if s.kind == "delivery" and s.eta is not None}
    oids = [s.order_id for s in stops if s.order_id]
    omap = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_(oids))).all()} if oids else {}
    vmap = {v.id: v for v in db.scalars(select(Vehicle)).all()}

    drv_by_veh: dict[int, str] = {}
    for d in db.scalars(select(Driver).where(Driver.vehicle_id.is_not(None))).all():
        drv_by_veh.setdefault(d.vehicle_id, d.name)
    for a in db.scalars(select(DriverVehicleAssignment).where(
            DriverVehicleAssignment.service_date == service_date)).all():
        dn = db.get(Driver, a.driver_id)
        if dn:
            drv_by_veh[a.vehicle_id] = dn.name

    # 逐車行對比:同一車可被多車行各自使用 → 按(車輛×車行)分欄,避免跨車行合併成假衝突
    by_veh: dict[tuple, list] = {}
    for s in stops:
        by_veh.setdefault((s.vehicle_id, s.fleet), []).append(s)

    vehicles = []
    for (vid, fl), slist in sorted(by_veh.items(), key=lambda kv: (kv[0][1] or "",
                                   vmap[kv[0][0]].plate or "" if kv[0][0] in vmap else "")):
        v = vmap.get(vid)
        # 接駁順序依 ETA(時間)從早到晚
        slist = sorted(slist, key=lambda s: (s.eta is None, s.eta))
        spans, trips = [], []
        for s in slist:
            st = _mins(s.eta)
            if st is not None:
                # 真實佔用時段 = 上車 → 下車(取自 auto_dispatch_stop);缺下車才退用固定估算
                end = drop_min.get((vid, s.order_id))
                if end is None or end <= st:
                    end = st + _DEFAULT_DUR_MIN
                spans.append((st, end, s.order_id))
        conflict_ids = set()
        spans.sort()
        for i in range(1, len(spans)):
            if spans[i][0] < spans[i - 1][1]:
                conflict_ids.add(spans[i][2]); conflict_ids.add(spans[i - 1][2])
        for s in slist:
            o = omap.get(s.order_id)
            trips.append({
                "order_id": s.order_id, "time": _hhmm(o.pickup_time) if o else None,
                "eta": _hhmm(s.eta), "passenger": o.passenger_name if o else None,
                "pickup": o.pickup_address if o else None, "dropoff": o.dropoff_address if o else None,
                "pax": o.pax if o else None,
                "welfare": (o.vehicle_type == "welfare" or o.need_wheelchair) if o else False,
                "status": "auto", "fleet": o.fleet if o else None,
                "support_fleet": (v.home_fleet if (v and o and (v.home_fleet or "") != (o.fleet or "")) else None),
                "conflict": s.order_id in conflict_ids,
            })
        vehicles.append({
            "vehicle_id": vid, "col_key": f"{vid}-{fl or ''}",
            "plate": v.plate if v else f"#{vid}",
            "driver": drv_by_veh.get(vid), "fleet": fl,   # 此路線所屬車行(逐車行對比)
            "on_duty": True, "trip_count": len(trips),
            "conflicts": len(conflict_ids), "trips": trips,
        })

    un = list(db.scalars(select(UnassignedRecord).where(
        UnassignedRecord.service_date == service_date)).all())
    uomap = {o.id: o for o in db.scalars(select(Order).where(
        Order.id.in_([u.order_id for u in un if u.order_id]))).all()} if un else {}
    unassigned = []
    for u in un:
        o = uomap.get(u.order_id)
        unassigned.append({
            "order_id": u.order_id, "time": _hhmm(o.pickup_time) if o else None,
            "passenger": o.passenger_name if o else None,
            "pickup": o.pickup_address if o else None, "dropoff": o.dropoff_address if o else None,
            "welfare": (o.vehicle_type == "welfare" or o.need_wheelchair) if o else False,
            "fleet": o.fleet if o else None, "reason": u.reason_code,
        })
    return {
        "service_date": service_date.isoformat(), "source": "auto",
        "vehicles": vehicles, "unassigned": unassigned, "unassigned_count": len(unassigned),
    }
