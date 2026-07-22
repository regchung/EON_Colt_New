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
from app.models.route import RouteStop
from app.models.vehicle import Vehicle
from app.services import matrix as matrix_svc
from app.services import roster as roster_svc

TW = timezone(timedelta(hours=8))
_HANDLING_SEC = 60        # 下車後上下車處理緩衝(秒)
_REACH_GRACE_SEC = 0      # 可達性容差(秒);>0 更寬鬆
_DEFAULT_DUR_MIN = 40   # 無 est 時的預設單趟占用(分)


def _hhmm(dt):
    return dt.astimezone(TW).strftime("%H:%M") if dt else None


def _mins(dt):
    if not dt:
        return None
    t = dt.astimezone(TW)
    return t.hour * 60 + t.minute


def _mins_to_hhmm(m: int | None) -> str | None:
    if m is None:
        return None
    return f"{m // 60:02d}:{m % 60:02d}"


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

    # 車輛 → 駕駛(當日出勤名冊)
    drv_by_veh: dict[int, str] = {
        vid: info["name"] for vid, info in roster_svc.driver_for_date(db, service_date).items()
        if info.get("name")
    }

    # 從 route_stop 取 VROOM 實際下車 ETA（delivery step）
    _delivery_eta: dict[int, str | None] = {}
    for rs in db.scalars(
        select(RouteStop).where(
            RouteStop.service_date == service_date,
            RouteStop.kind == "delivery",
            RouteStop.order_id.is_not(None),
            RouteStop.eta.is_not(None),
        )
    ).all():
        _delivery_eta[rs.order_id] = _hhmm(rs.eta)

    by_veh: dict[int, list[Order]] = {}
    for o in assigned:
        by_veh.setdefault(o.assigned_vehicle_id, []).append(o)

    def trip(o):
        return {
            "order_id": o.id,
            "pickup_time": _hhmm(o.pickup_time),   # DrCoLT 相容
            "time": _hhmm(o.pickup_time),           # 保留舊欄位
            "eta": _hhmm(o.eta),
            "dropoff_time": _delivery_eta.get(o.id) or (_hhmm(o.dropoff_time) if hasattr(o, "dropoff_time") else None),
            "passenger": o.passenger_name,
            "pickup_addr": o.pickup_address,        # DrCoLT 相容
            "pickup": o.pickup_address,             # 保留舊欄位
            "dropoff_addr": o.dropoff_address,      # DrCoLT 相容
            "dropoff": o.dropoff_address,           # 保留舊欄位
            "pickup_lng": o.pickup_lng,
            "pickup_lat": o.pickup_lat,
            "dropoff_lng": o.dropoff_lng,
            "dropoff_lat": o.dropoff_lat,
            "pax": o.pax,
            "need_welfare": o.vehicle_type == "welfare" or o.need_wheelchair,  # DrCoLT 相容
            "welfare": o.vehicle_type == "welfare" or o.need_wheelchair,
            "is_pool": o.pool_consent_at is not None and o.allow_pool,
            "is_standby": "候補" in (o.booking_source or ""),
            "status": o.status, "fleet": o.fleet,
            "support_fleet": o.support_fleet,
        }

    # OSRM 可達性衝突:用真實車程判「前趟下車後,趕不趕得到下一趟上車」(取代固定佔用重疊)。
    # 建一次 OSRM 矩陣(全體已派單的上/下車點)。
    _pi: dict[tuple, int] = {}
    _pts: list[tuple[float, float]] = []

    def _pt(lng, lat) -> int:
        k = (round(lng, 6), round(lat, 6))
        if k not in _pi:
            _pi[k] = len(_pts)
            _pts.append(k)
        return _pi[k]

    ord_idx: dict[int, tuple[int, int]] = {}
    for o in assigned:
        if o.pickup_lng is not None and o.dropoff_lng is not None:
            ord_idx[o.id] = (_pt(o.pickup_lng, o.pickup_lat), _pt(o.dropoff_lng, o.dropoff_lat))
    _mat = matrix_svc.build_matrix(_pts) if _pts else {"durations": []}
    _DUR = _mat.get("durations") or []

    def _drive(a, b) -> int:   # 兩點間車程(秒);缺值視為 0
        if a is None or b is None:
            return 0
        c = _DUR[a][b]
        return int(c) if c is not None else 0

    vehicles = []
    for vid in sorted(veh_ids, key=lambda x: (vmap[x].home_fleet or "" if x in vmap else "", vmap[x].plate or "" if x in vmap else "")):
        v = vmap.get(vid)
        # 依 VROOM 實際 ETA 排序（無 ETA 則用預約時間排尾）
        trips_o = sorted(by_veh.get(vid, []), key=lambda o: o.pickup_time or service_date)
        # 衝突偵測：
        # - VROOM 已排（有 eta）的訂單信任 VROOM，不重算物理可達性
        # - 手動插入（無 eta）的訂單才做 OSRM 可達性檢查
        conflict_ids = set()
        prev = None   # (order, pickup_idx, dropoff_idx, pickup_sec, has_eta)
        for o in trips_o:
            eta_dt = o.eta or o.pickup_time
            st = _mins(eta_dt)
            if st is None or o.id not in ord_idx:
                prev = None
                continue
            st_sec = st * 60
            pu, do = ord_idx[o.id]
            o_has_eta = o.eta is not None
            if prev is not None:
                po, ppu, pdo, pst, prev_has_eta = prev
                # 只有手動單（前後任一沒有 VROOM ETA）才做衝突檢查
                if not (o_has_eta and prev_has_eta):
                    reach = pst + _drive(ppu, pdo) + _HANDLING_SEC + _drive(pdo, pu)
                    if reach > st_sec + _REACH_GRACE_SEC:
                        conflict_ids.add(o.id)
                        conflict_ids.add(po.id)
            prev = (o, pu, do, st_sec, o_has_eta)
        trips = []
        for idx_t, o in enumerate(trips_o):
            t = trip(o)
            t["conflict"] = o.id in conflict_ids
            t["trip_index"] = idx_t   # 0=第一趟，不顯示遲到
            trips.append(t)
        vehicles.append({
            "vehicle_id": vid,
            "plate": v.plate if v else f"#{vid}",
            "driver": drv_by_veh.get(vid),
            "fleet": v.home_fleet if v else None,
            "vehicle_type": v.type if v else "normal",
            "on_duty": vid in duty,
            "trip_count": len(trips),
            "conflicts": len(conflict_ids),
            "has_conflict": len(conflict_ids) > 0,   # DrCoLT 相容
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

    drv_by_veh: dict[int, str] = {
        vid: info["name"] for vid, info in roster_svc.driver_for_date(db, service_date).items()
        if info.get("name")
    }

    # 共乘對:同一車上,若乙的上車 ETA ≤ 甲的下車 ETA → 共乘同行,重疊屬正常(VROOM 已驗可行)
    pool_pairs: set[tuple[int, int]] = set()
    veh_pickups: dict[int, list] = {}
    for s in stops:
        veh_pickups.setdefault(s.vehicle_id, []).append(s)
    for vid_key, plist in veh_pickups.items():
        plist_sorted = sorted(plist, key=lambda s: (s.eta is None, s.eta))
        for i, pa in enumerate(plist_sorted):
            da_min = drop_min.get((vid_key, pa.order_id))
            if da_min is None:
                continue
            for pb in plist_sorted[i + 1:]:
                pb_min = _mins(pb.eta)
                if pb_min is None:
                    continue
                if pb_min <= da_min:   # 乙上車時甲還在車上 → 共乘
                    pool_pairs.add((pa.order_id, pb.order_id))
                    pool_pairs.add((pb.order_id, pa.order_id))

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
                # 共乘同行的重疊屬正常,不視為衝突
                if (spans[i][2], spans[i - 1][2]) not in pool_pairs:
                    conflict_ids.add(spans[i][2]); conflict_ids.add(spans[i - 1][2])
        pool_oids = {oid for oid, _ in pool_pairs}
        for idx_t, s in enumerate(slist):
            o = omap.get(s.order_id)
            _nw = (o.vehicle_type == "welfare" or o.need_wheelchair) if o else False
            trips.append({
                "trip_index": idx_t,
                "order_id": s.order_id,
                "pickup_time": _hhmm(o.pickup_time) if o else None,
                "time": _hhmm(o.pickup_time) if o else None,
                "eta": _hhmm(s.eta),
                "dropoff_time": _mins_to_hhmm(drop_min.get((vid, s.order_id))),
                "passenger": o.passenger_name if o else None,
                "pickup_addr": o.pickup_address if o else None,
                "pickup": o.pickup_address if o else None,
                "dropoff_addr": o.dropoff_address if o else None,
                "dropoff": o.dropoff_address if o else None,
                "pickup_lng": o.pickup_lng if o else None,
                "pickup_lat": o.pickup_lat if o else None,
                "dropoff_lng": o.dropoff_lng if o else None,
                "dropoff_lat": o.dropoff_lat if o else None,
                "pax": o.pax if o else None,
                "need_welfare": _nw, "welfare": _nw,
                "is_pool": s.order_id in pool_oids,
                "pooled": s.order_id in pool_oids,
                "status": "auto", "fleet": o.fleet if o else None,
                "support_fleet": (v.home_fleet if (v and o and (v.home_fleet or "") != (o.fleet or "")) else None),
                "conflict": s.order_id in conflict_ids,
            })
        vehicles.append({
            "vehicle_id": vid, "col_key": f"{vid}-{fl or ''}",
            "plate": v.plate if v else f"#{vid}",
            "driver": drv_by_veh.get(vid), "fleet": fl,
            "vehicle_type": vmap[vid].type if vid in vmap else "normal",
            "on_duty": True, "trip_count": len(trips),
            "conflicts": len(conflict_ids),
            "has_conflict": len(conflict_ids) > 0,
            "trips": trips,
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
