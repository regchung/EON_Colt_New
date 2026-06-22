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
from app.services import fixed_route_match
from app.services import matrix as matrix_svc
from app.services import roster as roster_svc
from app.services import settings as settings_svc

DELIVERY_OFFSET = 1_000_000          # 用來區分 pickup/delivery 的 step id
PICKUP_SERVICE = 1200                # 上車前作業 20 分(每趟前後共 40 分工時)
DELIVERY_SERVICE = 1200             # 下車後作業 20 分
UNROUTABLE = 9_999_999               # 矩陣中無法到達的填充值
DAY_START = 6 * 3600                 # 接送服務時段起 06:00
DAY_END = 18 * 3600                  # 接送服務時段迄 18:00
MAX_WORK_SEC = 8 * 3600              # 每車每日工時上限 8h(行車+服務近似)
EXCL_CAP = 100                       # 「不共乘」維度容量;未同意共乘者佔滿 → 獨佔整車
LOCK_SKILL_BASE = 10000              # ongoing 訂單以「唯一技能」硬鎖原車(避開福祉 skill=1)
PIN_SKILL_BASE = 20000              # 固定行程以「唯一技能」硬綁指定車


TW = timezone(timedelta(hours=8))   # 台灣時區(資料庫存 UTC,排班以 +08 牆鐘換算)


def _secs_of_day(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _pickup_window(o: Order) -> tuple[int, int]:
    dt = o.pickup_time.astimezone(TW) if o.pickup_time.tzinfo else o.pickup_time
    start = _secs_of_day(dt.timetz())
    return start, start + (o.pickup_window_min or 0) * 60


def _is_welfare(o: Order) -> bool:
    # 派遣原則4:是否需福祉車「只看車型」(匯入時「福祉車」字樣→vehicle_type='welfare');
    # 其餘訂單不限車種(福祉車為能力超集,仍可兼接)。不再以 need_wheelchair 單獨判定。
    return o.vehicle_type == "welfare"


def _first_coord(*pairs) -> tuple[float, float] | None:
    """回傳第一組非空的 (lng, lat);用於 start/end 的優先序退化。"""
    for lng, lat in pairs:
        if lng is not None and lat is not None:
            return (lng, lat)
    return None


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
    # 僅納入「當日有出勤(班表)」的車輛;無班表資料的車保守視為不可用
    duty = roster_svc.available_vehicles(db, service_date)
    vehicles = list(
        db.scalars(
            select(Vehicle).where(Vehicle.active.is_(True), Vehicle.id.in_(duty.keys()))
            .order_by(Vehicle.id)
        ).all()
    ) if duty else []
    skipped = list(
        db.scalars(
            select(Order)
            .where(Order.service_date == service_date)
            .where(Order.status.in_(("imported", "scheduled")))
            .where((Order.pickup_lng.is_(None)) | (Order.dropoff_lng.is_(None)))
        ).all()
    )

    # 進行中(已上車、待下車)訂單:重排時必須鎖在「原指派車」、不可被搬走或重排上車。
    # 模型為 delivery-only Job(乘客已在車上佔位到下車),以唯一技能硬鎖原車。
    ongoing = list(
        db.scalars(
            select(Order)
            .where(Order.service_date == service_date)
            .where(Order.status == "ongoing")
            .where(Order.assigned_vehicle_id.is_not(None))
            .where(Order.dropoff_lng.is_not(None), Order.dropoff_lat.is_not(None))
            .order_by(Order.assigned_vehicle_id, Order.dispatch_seq)
        ).all()
    )
    # 有進行中行程的車一定在出勤中:即使班表未涵蓋,也強制納入問題
    veh_ids = {v.id for v in vehicles}
    extra_ids = {o.assigned_vehicle_id for o in ongoing} - veh_ids
    if extra_ids:
        vehicles.extend(
            db.scalars(
                select(Vehicle).where(Vehicle.id.in_(extra_ids), Vehicle.active.is_(True))
                .order_by(Vehicle.id)
            ).all()
        )

    # 固定行程:把符合規則的訂單釘給指定司機的車(以唯一技能硬綁);指定車強制納入
    fr = fixed_route_match.match_for_date(db, service_date)
    pend_ids = {o.id for o in orders}
    fixed_pins = {oid: vid for oid, vid in fr["pins"].items() if oid in pend_ids}
    pin_vehicle_ids = set(fixed_pins.values())
    extra_pin = pin_vehicle_ids - {v.id for v in vehicles}
    if extra_pin:
        vehicles.extend(
            db.scalars(
                select(Vehicle).where(Vehicle.id.in_(extra_pin), Vehicle.active.is_(True))
                .order_by(Vehicle.id)
            ).all()
        )
        pin_vehicle_ids &= {v.id for v in vehicles}  # 仍取不到(停用)者放棄釘選
        fixed_pins = {o: v for o, v in fixed_pins.items() if v in pin_vehicle_ids}

    if not orders:
        return {"error": "該日沒有可排班的已編碼訂單", "skipped_no_coords": [o.id for o in skipped]}
    if not vehicles:
        return {"error": "該日無出勤車輛:請先於「班表」設定當日上班車輛(或排除例外)。"}

    # 2) 收集座標點(去重)→ 索引
    points: list[tuple[float, float]] = []
    index: dict[tuple[float, float], int] = {}

    def pt_index(lng: float, lat: float) -> int:
        key = (round(lng, 6), round(lat, 6))
        if key not in index:
            index[key] = len(points)
            points.append(key)
        return index[key]

    # 車輛出車起點 / 收車終點(start≠end);缺則退化到 depot
    veh_se: dict[int, tuple[int, int]] = {}
    for v in vehicles:
        s = _first_coord((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
        e = _first_coord((v.end_lng, v.end_lat), (v.start_lng, v.start_lat),
                         (v.depot_lng, v.depot_lat))
        if s is not None:
            si = pt_index(*s)
            ei = pt_index(*e) if e is not None else si
            veh_se[v.id] = (si, ei)
    ord_pts = {}
    for o in orders:
        ord_pts[o.id] = (
            pt_index(o.pickup_lng, o.pickup_lat),
            pt_index(o.dropoff_lng, o.dropoff_lat),
        )
    # 進行中訂單只剩「下車點」需排(上車已完成)
    ongoing_pts = {o.id: pt_index(o.dropoff_lng, o.dropoff_lat) for o in ongoing}
    lock_vehicles = {o.assigned_vehicle_id for o in ongoing}

    # 3) 取 OSRM 行車時間矩陣
    m = matrix_svc.build_matrix(points)
    durations = m["durations"]
    arr = np.array(
        [[int(round(c)) if c is not None else UNROUTABLE for c in row] for row in durations],
        dtype=np.uint32,
    )

    # 4) 組 VROOM 問題(營運參數由系統設定提供,可由管理者於設定頁調整)
    prm = settings_svc.dispatch_params(db)
    day_start, day_end = prm["day_start_sec"], prm["day_end_sec"]
    day_end_op = day_end + prm.get("completion_buffer_sec", 0)   # 車輛可延後完成的營運上限
    problem = vroom.Input()
    problem.set_durations_matrix("car", arr)

    for v in vehicles:
        # 班別時段來自當日班表(無則用服務時段),再與服務時段取交集
        rs, re = duty.get(v.id, (None, None))
        win_start = max(day_start, rs) if rs is not None else day_start
        # 營運迄:可延後到 day_end_op 以完成 18:00 前上車的趟次;班別迄(re)若有設定則尊重
        win_end = min(day_end_op, re) if re is not None else day_end_op
        skills = {1} if v.type == "welfare" else set()
        if v.id in lock_vehicles:
            skills.add(LOCK_SKILL_BASE + v.id)   # 鎖住其進行中行程的專屬技能
        if v.id in pin_vehicle_ids:
            skills.add(PIN_SKILL_BASE + v.id)    # 固定行程:接受被釘給此車的單
        kwargs = dict(
            id=v.id,
            profile="car",
            capacity=[max(1, v.seats or 1), EXCL_CAP],  # [座位, 不共乘維度]
            skills=skills,
            time_window=vroom.TimeWindow(win_start, win_end),
            max_travel_time=prm["max_work_sec"],
        )
        if v.id in veh_se:
            kwargs["start"], kwargs["end"] = veh_se[v.id]
        problem.add_vehicle(vroom.Vehicle(**kwargs))

    out_of_service = 0
    tasks_added = 0
    for o in orders:
        p_idx, d_idx = ord_pts[o.id]
        pw_start, pw_end = _pickup_window(o)
        # 上車須落在服務時段 06:00–18:00;之外者不派(視為服務時段外)
        if pw_start < day_start or pw_start > day_end:
            out_of_service += 1
            continue
        pw_end = min(pw_end, day_end)   # 上車不得晚於 18:00
        # 共乘需同意(設定可關閉):需同意但未同意者第二維度佔滿 → 獨佔整車。
        # 派遣原則1:固定趟次可共乘 → 強制可併車(excl=1),不受同意限制。
        if o.id in fixed_pins:
            excl = 1
        else:
            excl = EXCL_CAP if (prm["require_consent"] and not o.allow_pool) else 1
        pickup = vroom.ShipmentStep(
            id=o.id, location=p_idx, default_service=prm["setup_sec"],
            time_windows=[vroom.TimeWindow(pw_start, pw_end)],
        )
        delivery = vroom.ShipmentStep(
            id=o.id + DELIVERY_OFFSET, location=d_idx, default_service=prm["teardown_sec"],
        )
        sk = {1} if _is_welfare(o) else set()
        if o.id in fixed_pins:
            sk.add(PIN_SKILL_BASE + fixed_pins[o.id])   # 固定行程:硬綁指定車
        problem.add_shipment(
            pickup, delivery,
            amount=vroom.Amount([max(1, o.pax or 1), excl]),
            skills=sk,
            priority=80 if o.id in fixed_pins else 50,   # 固定行程優先排入
        )
        tasks_added += 1

    # 進行中訂單:delivery-only job,以專屬技能硬鎖原車(乘客已在車上,初始載重佔位到下車)
    for o in ongoing:
        excl = EXCL_CAP if (prm["require_consent"] and not o.allow_pool) else 1
        skills = {LOCK_SKILL_BASE + o.assigned_vehicle_id}
        if _is_welfare(o):
            skills.add(1)
        problem.add_job(vroom.Job(
            id=o.id,
            location=ongoing_pts[o.id],
            delivery=vroom.Amount([max(1, o.pax or 1), excl]),
            skills=skills,
            default_service=prm["teardown_sec"],
            priority=100,  # 已在車上,務必完成下車
        ))
        tasks_added += 1

    # 過濾後無任何可排任務(例:當日訂單全在服務時段外)→ 優雅回覆,勿讓 VROOM 崩潰
    if tasks_added == 0:
        return {
            "service_date": service_date.isoformat(),
            "error": "該日無可排入的任務(訂單可能全在服務時段外或已完成)。",
            "orders_total": len(orders), "assigned": 0,
            "out_of_service": out_of_service,
            "skipped_no_coords": [o.id for o in skipped],
        }

    sol = problem.solve(exploration_level=5, nb_threads=4)

    # 5) 寫回結果(先清空當日待排訂單的舊指派,確保可重複排班)
    for o in orders:
        o.assigned_vehicle_id = None
        o.dispatch_seq = None
        o.eta = None
        o.status = "imported"

    by_id = {o.id: o for o in orders}
    ongoing_by_id = {o.id: o for o in ongoing}
    midnight = datetime.combine(service_date, time(0), tzinfo=TW)
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
        elif stype == "job" and sid == sid:
            # 進行中訂單的下車(delivery-only job);保持 ongoing 狀態,僅更新預計下車與路線
            oid = int(sid)
            o = ongoing_by_id.get(oid)
            if o:
                o.eta = eta_dt
                kind = "delivery"
                addr = o.dropoff_address
                routes_report[vid].append(
                    {"order_id": oid, "type": "下車(進行中)", "eta": arr_hhmm, "addr": addr}
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
        "ongoing_locked": len(ongoing),
        "fixed_pinned": len(fixed_pins),
        "out_of_service": out_of_service,
        "skipped_no_coords": [o.id for o in skipped],
        "total_duration_sec": int(sol.summary.duration),
        "routes": routes_report,
    }
