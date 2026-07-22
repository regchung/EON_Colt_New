"""VROOM 自動排班:把某日訂單最佳化分配給車輛。

模型對照:
- 每張訂單   = VROOM shipment(pickup 上車 → delivery 下車)
- 福祉車需求 = skills {1}(訂單與福祉車都帶 1;福祉車能力為超集,可兼接一般單)
- 共乘座位   = amount [pax] + 車輛 capacity [seats]
- 預約時間   = pickup time_windows
- 班別       = 車輛 time_window
- 行車時間   = 自架 OSRM 矩陣(app.services.matrix)

共乘規則:同一上車地址的訂單自動視為同意共乘;其餘訂單依 pool_consent_at 判定。
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

log = logging.getLogger(__name__)

import numpy as np
import vroom
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.order import Order
from app.models.route import RouteStop
from app.models.unassigned_record import UnassignedRecord
from app.models.vehicle import Vehicle
from app.services import fixed_route_match
from app.services import matrix as matrix_svc
from app.services import roster as roster_svc
from app.services import calibration as calib_svc
from app.services import settings as settings_svc

DELIVERY_OFFSET = 1_000_000          # 用來區分 pickup/delivery 的 step id
UNROUTABLE = 9_999_999               # 矩陣中無法到達的填充值
DAY_START = 6 * 3600                 # 接送服務時段起 06:00
DAY_END = 18 * 3600                  # 接送服務時段迄 18:00
EXCL_CAP = 100                       # 「不共乘」維度容量;未同意共乘者佔滿 → 獨佔整車
LOCK_SKILL_BASE = 10000              # ongoing 訂單以「唯一技能」硬鎖原車
PIN_SKILL_BASE = 20000               # 固定行程以「唯一技能」硬綁指定車
DISTRICT_SKILL_BASE = 40000          # 地區服務技能基底

# 新北市 29 行政區，索引對應到技能 ID
NTPC_DISTRICTS = [
    "板橋區", "三重區", "中和區", "永和區", "新莊區", "新店區",
    "樹林區", "鶯歌區", "三峽區", "淡水區", "汐止區", "瑞芳區",
    "土城區", "蘆洲區", "林口區", "深坑區", "石碇區", "坪林區",
    "三芝區", "石門區", "八里區", "平溪區", "雙溪區", "貢寮區",
    "金山區", "萬里區", "烏來區", "泰山區", "五股區",
    # 桃園市（跨縣市服務）
    "中壢區", "大園區", "桃園區",
]
_DIST_IDX: dict[str, int] = {d: i for i, d in enumerate(NTPC_DISTRICTS)}

# 鄰近行政區對照表（依新北市地圖實際接壤關係）
DISTRICT_NEIGHBORS: dict[str, set[str]] = {
    # 西部平原核心（人口密集、互通頻繁）
    "板橋區": {"三重區","新莊區","中和區","永和區","樹林區","土城區"},
    "三重區": {"板橋區","新莊區","蘆洲區"},
    "中和區": {"板橋區","永和區","新店區","土城區"},
    "永和區": {"板橋區","中和區"},
    "新莊區": {"板橋區","三重區","蘆洲區","泰山區","五股區"},
    "土城區": {"板橋區","中和區","新店區","樹林區","三峽區"},
    "樹林區": {"板橋區","土城區","三峽區","鶯歌區"},
    "鶯歌區": {"樹林區","三峽區"},
    "三峽區": {"樹林區","鶯歌區","土城區","烏來區"},
    # 北海岸（台2線串聯）
    "淡水區": {"三芝區","八里區"},
    "三芝區": {"淡水區","石門區"},
    "石門區": {"三芝區","金山區"},
    "金山區": {"石門區","萬里區"},
    "萬里區": {"金山區"},                      # 隔山，汐止無直通路
    # 觀音山西側（台15/台64 路網）
    "八里區": {"淡水區","五股區","林口區"},    # 隔河，蘆洲無橋直通
    "蘆洲區": {"三重區","新莊區","五股區"},    # 隔河，八里無橋直通
    "五股區": {"新莊區","蘆洲區","八里區","林口區","泰山區"},
    "泰山區": {"新莊區","五股區","林口區"},
    "林口區": {"五股區","八里區","泰山區"},    # 觀音山阻隔，淡水無直通
    # 東北山區（台2丁/台62 路網）
    "汐止區": {"瑞芳區","平溪區","石碇區"},   # 萬里隔山無直路；深坑隔南港山系
    "瑞芳區": {"汐止區","平溪區","雙溪區","貢寮區"},
    "平溪區": {"汐止區","瑞芳區","雙溪區","石碇區"},
    "雙溪區": {"瑞芳區","平溪區","貢寮區"},
    "貢寮區": {"瑞芳區","雙溪區"},
    # 東南山區（北宜路網）
    "新店區": {"中和區","土城區","深坑區","石碇區","坪林區","烏來區"},
    "深坑區": {"新店區","石碇區"},             # 汐止隔南港山系無直通
    "石碇區": {"汐止區","平溪區","深坑區","新店區","坪林區","烏來區"},
    "坪林區": {"新店區","石碇區"},
    "烏來區": {"新店區","三峽區","石碇區"},
}

def _expand_district_zone(home: str, levels: int) -> set[str]:
    """從 home 出發，BFS 展開 levels 層鄰近行政區（levels=0 僅自身，1=鄰近一層，…）。"""
    zone: set[str] = {home}
    frontier: set[str] = {home}
    for _ in range(levels):
        next_frontier: set[str] = set()
        for d in frontier:
            next_frontier |= DISTRICT_NEIGHBORS.get(d, set()) - zone
        zone |= next_frontier
        frontier = next_frontier
        if not frontier:
            break
    return zone

# 內建行政區代表座標（與前端同步）
_DIST_COORDS: dict[str, tuple[float, float]] = {
    "板橋區":(121.4628,25.0136),"三重區":(121.4867,25.0617),"中和區":(121.5030,24.9986),
    "永和區":(121.5198,25.0145),"新莊區":(121.4498,25.0399),"新店區":(121.5415,24.9723),
    "樹林區":(121.4222,24.9939),"鶯歌區":(121.3475,24.9555),"三峽區":(121.3720,24.9365),
    "淡水區":(121.4512,25.1695),"汐止區":(121.6557,25.0637),"瑞芳區":(121.8028,25.1085),
    "土城區":(121.4452,24.9740),"蘆洲區":(121.4766,25.0866),"林口區":(121.3889,25.0789),
    "深坑區":(121.6145,24.9916),"石碇區":(121.6603,24.9762),"坪林區":(121.7148,24.9347),
    "三芝區":(121.5031,25.2559),"石門區":(121.5690,25.2937),"八里區":(121.3964,25.1564),
    "平溪區":(121.7379,25.0213),"雙溪區":(121.8686,25.0417),"貢寮區":(121.9035,25.0247),
    "金山區":(121.6378,25.2238),"萬里區":(121.6890,25.1805),"烏來區":(121.5487,24.8680),
    "泰山區":(121.4320,25.0564),"五股區":(121.4487,25.0780),"木柵區":(121.5700,24.9989),
    "中壢區":(121.2244,24.9706),"大園區":(121.1561,25.0378),"桃園區":(121.3010,24.9937),
}

def _nearest_district(lng: float | None, lat: float | None) -> str | None:
    """由座標找最近行政區（歐氏距離）。"""
    if lng is None or lat is None:
        return None
    best, best_d = None, float("inf")
    for d, (lo, la) in _DIST_COORDS.items():
        dist = (lo - lng) ** 2 + (la - lat) ** 2
        if dist < best_d:
            best_d = dist; best = d
    return best

def _vehicle_zone_skills(v) -> set[int]:
    """車輛第一輪地區技能：
    - 有指定 district → 只接該區（嚴格限制）
    - 無指定 district → 主場 + 鄰近區（由座標推算）
    - 無座標/主場 → 全區
    """
    # 有明確指定服務地區 → 嚴格限定單區
    if v.district and v.district in _DIST_IDX:
        return {DISTRICT_SKILL_BASE + _DIST_IDX[v.district]}

    # 無指定 → 由停放座標推算主場 + 鄰近區
    home = _nearest_district(v.start_lng, v.start_lat) or \
           _nearest_district(v.depot_lng, v.depot_lat)
    if home is None:
        return {DISTRICT_SKILL_BASE + i for i in range(len(NTPC_DISTRICTS))}
    nearby = {home} | DISTRICT_NEIGHBORS.get(home, set())
    skills = {DISTRICT_SKILL_BASE + _DIST_IDX[d] for d in nearby if d in _DIST_IDX}
    return skills or {DISTRICT_SKILL_BASE + i for i in range(len(NTPC_DISTRICTS))}

TW = timezone(timedelta(hours=8))
MIN_MAX_RIDE_SEC = 2400              # 最長乘車時間下限 40 分
import math as _math


# ─────────────────────────────────────────────────────────────────────────────
# ① 貪婪首趟預釘（移植自雲DrCOLT）
#    為每輛車從起點出發挑最近（行駛時間最短）且時間窗相容的第一趟訂單，
#    給予 PIN_SKILL_BASE 釘定提示，讓 VROOM 有更好的初始解。
# ─────────────────────────────────────────────────────────────────────────────
def _pin_first_trips_greedy(
    vehicles: list,
    orders: list[Order],
    index: dict,
    arr,           # np.ndarray
    duty: dict,
    day_start: int,
    day_end: int,
    existing_pins: dict[int, int],  # 固定行程已釘的 order_id→vehicle_id
    early_sec: int = 900,
    late_sec: int = 1800,
) -> dict[int, int]:
    """貪婪預釘每輛車第一趟：
    - 福祉車只挑福祉訂單（vehicle_type=='welfare'）
    - 一般車只挑一般訂單
    - 候選訂單必須在車輛出車起點所在行政區或其鄰近區內
    - 在此範圍內再以行駛時間最短者優先
    回傳 {order_id: vehicle_id}，已在 existing_pins 中的訂單不重複釘。
    """
    LATE_SEC = 30 * 60   # 最晚允許比時間窗晚 30 分出發
    pinned_order_ids: set[int] = set(existing_pins.keys())
    pinned_vehicle_ids: set[int] = set(existing_pins.values())
    greedy: dict[int, int] = {}

    all_eligible = [
        o for o in orders
        if o.id not in pinned_order_ids
        and (round(o.pickup_lng, 6), round(o.pickup_lat, 6)) in index
    ]

    for v in sorted(vehicles, key=lambda x: x.id):
        if v.id in pinned_vehicle_ids:
            continue
        s = _first_coord((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
        if s is None:
            continue
        v_idx = index.get((round(s[0], 6), round(s[1], 6)))
        if v_idx is None:
            continue

        # 出車起點鄰近區集合（供地理篩選）
        v_home = _nearest_district(s[0], s[1])
        v_zones: set[str] = ({v_home} | DISTRICT_NEIGHBORS.get(v_home, set())) if v_home else set()

        rs, re = duty.get(v.id, (None, None))
        v_start = max(day_start, rs) if rs is not None else day_start

        is_welfare_veh = (v.type == "welfare")

        best_o, best_dur = None, float("inf")
        for o in all_eligible:
            if o.id in pinned_order_ids:
                continue
            # 車型配對：福祉車只接福祉單，一般車只接一般單
            if _is_welfare(o) != is_welfare_veh:
                continue
            o_idx = index.get((round(o.pickup_lng, 6), round(o.pickup_lat, 6)))
            if o_idx is None:
                continue
            dur = float(arr[v_idx][o_idx])
            if dur >= UNROUTABLE:
                continue
            # 地理篩選：上車點必須在出車起點的行政區或鄰近區內
            if v_zones:
                o_district = _nearest_district(o.pickup_lng, o.pickup_lat)
                if o_district and o_district not in v_zones:
                    continue
            # 時間窗相容：能在訂單時間窗結束+LATE_SEC前抵達
            pw_start, pw_end = _pickup_window(o, early_sec, late_sec)
            if v_start + dur > pw_end + LATE_SEC:
                continue
            if dur < best_dur:
                best_dur = dur
                best_o = o

        if best_o is not None:
            greedy[best_o.id] = v.id
            pinned_order_ids.add(best_o.id)
            pinned_vehicle_ids.add(v.id)

    # Fallback：對仍未拿到釘單的車，放寬地理限制（保留時間窗），取最近可行訂單補釘
    for v in sorted(vehicles, key=lambda x: x.id):
        if v.id in pinned_vehicle_ids:
            continue
        s = _first_coord((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
        if s is None:
            continue
        v_idx = index.get((round(s[0], 6), round(s[1], 6)))
        if v_idx is None:
            continue
        rs, re = duty.get(v.id, (None, None))
        v_start = max(day_start, rs) if rs is not None else day_start
        is_welfare_veh = (v.type == "welfare")
        best_o, best_dur = None, float("inf")
        for o in all_eligible:
            if o.id in pinned_order_ids:
                continue
            if _is_welfare(o) != is_welfare_veh:
                continue
            o_idx = index.get((round(o.pickup_lng, 6), round(o.pickup_lat, 6)))
            if o_idx is None:
                continue
            dur = float(arr[v_idx][o_idx])
            if dur >= UNROUTABLE:
                continue
            # 保留時間窗檢查，放寬地理區限制
            pw_start, pw_end = _pickup_window(o, early_sec, late_sec)
            if v_start + dur > pw_end + LATE_SEC:
                continue
            if dur < best_dur:
                best_dur = dur
                best_o = o
        if best_o is not None:
            greedy[best_o.id] = v.id
            pinned_order_ids.add(best_o.id)
            pinned_vehicle_ids.add(v.id)

    return greedy


# 貪婪首趟抵達時間快取：{order_id: estimated_arrival_sec}
# 由 run_dispatch 填入，供 _make_shipment 縮緊時間窗用
_greedy_pin_arrival: dict[int, int] = {}


# ─────────────────────────────────────────────────────────────────────────────
# ② 每車型動態 max_tasks（移植自雲DrCOLT）
# ─────────────────────────────────────────────────────────────────────────────
def _calc_max_tasks(order_cnt: int, veh_cnt: int, buffer: float = 1.1,
                    hard_cap: int | None = None) -> int | None:
    if veh_cnt <= 0:
        return None
    mt = max(_math.ceil(order_cnt / veh_cnt * buffer) * 2, 10)
    return min(hard_cap, mt) if hard_cap is not None else mt


def _max_ride_upper(direct_sec: int, pw_end: int, factor: float, grace_sec: int) -> int | None:
    if not factor or factor <= 0 or direct_sec >= UNROUTABLE:
        return None
    max_ride = max(MIN_MAX_RIDE_SEC, int(direct_sec * factor) + grace_sec)
    return pw_end + max_ride


def _secs_of_day(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _pickup_window(o: Order, early_sec: int = 0, late_sec: int | None = None) -> tuple[int, int]:
    dt = o.pickup_time.astimezone(TW) if o.pickup_time.tzinfo else o.pickup_time
    sched = _secs_of_day(dt.timetz())
    window_late = (o.pickup_window_min or 0) * 60 if late_sec is None else late_sec
    return max(0, sched - early_sec), sched + window_late


def _is_welfare(o: Order) -> bool:
    return o.vehicle_type == "welfare"


def _vehicles_with_driver(db: Session, service_date: date) -> set[int]:
    ids = {vid for (vid,) in db.execute(
        select(Driver.vehicle_id)
        .where(Driver.vehicle_id.is_not(None), Driver.suspended.is_(False))).all()}
    ids |= {vid for (vid, susp) in db.execute(
        select(DriverVehicleAssignment.vehicle_id, Driver.suspended)
        .join(Driver, Driver.id == DriverVehicleAssignment.driver_id)
        .where(DriverVehicleAssignment.service_date == service_date)).all() if not susp}
    return ids



def _first_coord(*pairs) -> tuple[float, float] | None:
    for lng, lat in pairs:
        if lng is not None and lat is not None:
            return (lng, lat)
    return None


def _vehicle_district_skills(district: str | None) -> set[int]:
    """有指定地區的車：帶該地區技能（只接該區訂單）。
    未指定地區的車：帶全部地區技能（可接任何地區訂單）。"""
    if district and district in _DIST_IDX:
        return {DISTRICT_SKILL_BASE + _DIST_IDX[district]}
    return {DISTRICT_SKILL_BASE + i for i in range(len(NTPC_DISTRICTS))}


def _order_district_skill(customer_region: str | None) -> int | None:
    """訂單有指定客戶地區且在新北市行政區清單內：回傳對應技能 ID，否則 None（不限地區）。"""
    if customer_region and customer_region in _DIST_IDX:
        return DISTRICT_SKILL_BASE + _DIST_IDX[customer_region]
    return None


def _shared_pickup_addresses(orders: list[Order]) -> set[str]:
    """同一日中，上車地址出現超過一次者 → 自動視為同意共乘。"""
    counts = Counter((o.pickup_address or "").strip() for o in orders)
    return {addr for addr, n in counts.items() if addr and n > 1}


def run_dispatch(db: Session, service_date: date) -> dict:
    # 1) 取當日可排訂單(已地理編碼)
    orders = list(
        db.scalars(
            select(Order)
            .where(Order.service_date == service_date)
            .where(Order.status.in_(("imported", "scheduled")))
            .where(Order.pickup_lng.is_not(None), Order.pickup_lat.is_not(None),
                   Order.dropoff_lng.is_not(None), Order.dropoff_lat.is_not(None))
            .order_by(Order.id)
        ).all()
    )

    # 同一上車地址自動共乘
    shared_addrs = _shared_pickup_addresses(orders)

    # 可用車輛
    duty = roster_svc.available_vehicles(db, service_date)
    if not duty:
        duty = {vid: (None, None) for (vid,) in db.execute(
            select(Vehicle.id).where(Vehicle.active.is_(True))).all()}

    # 排除「停派」車輛(suspended)— 不納入自動派遣。
    susp_veh = {vid for (vid,) in db.execute(
        select(Vehicle.id).where(Vehicle.suspended.is_(True))).all()}
    if susp_veh:
        duty = {vid: w for vid, w in duty.items() if vid not in susp_veh}

    driver_veh = _vehicles_with_driver(db, service_date)
    if driver_veh:
        duty = {vid: w for vid, w in duty.items() if vid in driver_veh}


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

    # 進行中訂單（鎖定原車）
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
    veh_ids = {v.id for v in vehicles}
    extra_ids = {o.assigned_vehicle_id for o in ongoing} - veh_ids
    if extra_ids:
        vehicles.extend(
            db.scalars(
                select(Vehicle).where(Vehicle.id.in_(extra_ids), Vehicle.active.is_(True))
                .order_by(Vehicle.id)
            ).all()
        )

    # 固定行程:把符合規則的訂單釘給指定司機的車(以唯一技能硬綁)。
    # 指定車必須出現在出勤名冊(duty)中;未排班的車視為不可用,釘選取消、訂單退回一般排班。
    fr = fixed_route_match.match_for_date(db, service_date)
    pend_ids = {o.id for o in orders}
    duty_vids = {v.id for v in vehicles}
    fixed_pins = {
        oid: vid for oid, vid in fr["pins"].items()
        if oid in pend_ids and vid in duty_vids
    }
    pin_vehicle_ids = set(fixed_pins.values())
    extra_pin = pin_vehicle_ids - {v.id for v in vehicles}
    if extra_pin:
        vehicles.extend(
            db.scalars(
                select(Vehicle).where(Vehicle.id.in_(extra_pin), Vehicle.active.is_(True))
                .order_by(Vehicle.id)
            ).all()
        )
        pin_vehicle_ids &= {v.id for v in vehicles}
        fixed_pins = {o: v for o, v in fixed_pins.items() if v in pin_vehicle_ids}

    if not orders:
        return {"error": "該日沒有可排班的已編碼訂單", "skipped_no_coords": [o.id for o in skipped]}
    if not vehicles:
        return {"error": "該日無出勤車輛:請先於「班表」設定當日上班車輛(或排除例外)。"}

    # 2) 座標索引
    points: list[tuple[float, float]] = []
    index: dict[tuple[float, float], int] = {}

    def pt_index(lng: float, lat: float) -> int:
        key = (round(lng, 6), round(lat, 6))
        if key not in index:
            index[key] = len(points)
            points.append(key)
        return index[key]

    # 無座標車輛的備用起點：當日上車點中心
    fallback_coord: tuple[float, float] | None = None
    if orders:
        lngs = [o.pickup_lng for o in orders if o.pickup_lng]
        lats = [o.pickup_lat for o in orders if o.pickup_lat]
        if lngs:
            fallback_coord = (sum(lngs)/len(lngs), sum(lats)/len(lats))

    # 車輛出車起點 / 收車終點(start≠end);缺則退化到 depot，再缺用備用中心點
    veh_se: dict[int, tuple[int, int]] = {}
    for v in vehicles:
        s = _first_coord((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
        if s is None and fallback_coord:
            s = fallback_coord
        e = _first_coord((v.end_lng, v.end_lat), (v.start_lng, v.start_lat),
                         (v.depot_lng, v.depot_lat))
        if e is None and fallback_coord:
            e = fallback_coord
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
    ongoing_pts = {o.id: pt_index(o.dropoff_lng, o.dropoff_lat) for o in ongoing}
    lock_vehicles = {o.assigned_vehicle_id for o in ongoing}

    # 3) OSRM 矩陣
    m = matrix_svc.build_matrix(points)
    durations = m["durations"]
    arr = np.array(
        [[int(round(c)) if c is not None else UNROUTABLE for c in row] for row in durations],
        dtype=np.uint32,
    )

    # 4) VROOM 問題
    prm = settings_svc.dispatch_params(db)
    day_start, day_end = prm["day_start_sec"], prm["day_end_sec"]
    margin = prm.get("driver_margin_sec", 0)
    veh_day_start = day_start - margin
    veh_day_end = day_end + prm.get("completion_buffer_sec", 0)
    early_sec = int(prm.get("pickup_early_min", 15) * 60)
    late_sec  = int(prm.get("pickup_window_min", 30) * 60)

    # ── TDX 即時路況調整（設定 tdx_traffic_enabled=true 才生效）──────
    if prm.get("tdx_traffic_enabled", False):
        try:
            from app.services import tdx_traffic as _tdx
            arr = _tdx.apply_to_matrix(arr, points)
            if prm.get("tdx_window_adjust", False):
                _cong = _tdx.get_congestion_level()
                late_sec = int(late_sec * (1 + _cong * 0.5))
                log.info(f"TDX 路況調整：壅塞={_cong:.2f}, late_sec={late_sec}s")
        except Exception as _e:
            log.warning(f"TDX 路況調整略過: {_e}")

    # ① 貪婪首趟預釘（移植自雲DrCOLT）
    greedy_pins = _pin_first_trips_greedy(
        vehicles, orders, index, arr, duty,
        day_start, day_end, fixed_pins,
        early_sec=early_sec, late_sec=late_sec,
    )

    # 計算每個貪婪釘定訂單的車輛估算抵達時間，存入模組快取
    # 供後續 _add_shipment 縮緊時間窗，強制 VROOM 排在第一趟
    _greedy_pin_arrival.clear()
    for oid, vid in greedy_pins.items():
        v = next((v for v in vehicles if v.id == vid), None)
        o = next((o for o in orders if o.id == oid), None)
        if v and o:
            s = _first_coord((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
            if s:
                v_idx = index.get((round(s[0], 6), round(s[1], 6)))
                o_idx = index.get((round(o.pickup_lng, 6), round(o.pickup_lat, 6)))
                if v_idx is not None and o_idx is not None:
                    rs, _ = duty.get(vid, (None, None))
                    v_start = max(day_start, rs) if rs is not None else day_start
                    travel = int(arr[v_idx][o_idx])
                    pw_start, _ = _pickup_window(o, early_sec, late_sec)
                    # 車輛可能比訂單時間窗早抵達，取兩者較大值避免緊縮窗錯位
                    _greedy_pin_arrival[oid] = max(v_start + travel, pw_start)

    # 合併固定行程 + 貪婪首趟
    all_pins = {**greedy_pins, **fixed_pins}   # fixed_pins 優先（覆蓋 greedy）
    all_pin_vehicle_ids = set(all_pins.values())

    # ② 新派遣架構：兩輪分離+混合
    #   第一輪 1a：福祉車 ← 福祉訂單（分開 VROOM）
    #   第一輪 1b：一般車 ← 一般訂單（分開 VROOM）
    #   第二輪：全車 ← 剩餘所有未派訂單（混合優化，無車型/地區限制）
    #   每台車 max_tasks = 15（可由系統設定調整）

    welfare_vehs  = [v for v in vehicles if v.type == "welfare"]
    normal_vehs   = [v for v in vehicles if v.type != "welfare"]
    welfare_accept_normal = prm.get("welfare_accept_normal", True)
    MAX_TASKS = prm.get("max_tasks_per_vehicle", 15)

    fixed_cost = prm.get("vehicle_fixed_cost", 500000)
    veh_costs = vroom.VehicleCosts(fixed=fixed_cost, per_hour=3600)

    svc_cal = calib_svc.service_map(db)
    default_service_sec = prm["setup_sec"] + prm["teardown_sec"]
    svc_factor = prm.get("service_factor", 1.0) or 1.0

    def _svc_split(o) -> tuple[int, int]:
        sec = calib_svc.effective_service_sec(svc_cal, o.fleet, _is_welfare(o), default_service_sec)
        sec = int(sec * svc_factor)
        return sec // 2, sec - sec // 2

    def _make_vehicle(v, zone_restrict: bool = True) -> vroom.Vehicle:
        """zone_restrict=True（第一輪）：本區+鄰近區技能；False（第二輪）：全區開放。"""
        rs, re = duty.get(v.id, (None, None))
        ws = max(veh_day_start, rs) if rs is not None else veh_day_start
        we = min(veh_day_end, re) if re is not None else veh_day_end
        sk = {1} if v.type == "welfare" else set()
        if v.id in lock_vehicles:
            sk.add(LOCK_SKILL_BASE + v.id)
        if v.id in all_pin_vehicle_ids:
            sk.add(PIN_SKILL_BASE + v.id)
        # 地區技能：第一輪限制主場+鄰近區，第二輪全區
        if zone_restrict:
            sk |= _vehicle_zone_skills(v)
        else:
            sk |= {DISTRICT_SKILL_BASE + i for i in range(len(NTPC_DISTRICTS))}
        kw = dict(id=v.id, profile="car",
                  capacity=[max(1, v.seats or 1), EXCL_CAP],
                  skills=sk,
                  time_window=vroom.TimeWindow(ws, we),
                  max_travel_time=prm["max_work_sec"],
                  max_tasks=MAX_TASKS,
                  costs=veh_costs)
        if v.id in veh_se:
            kw["start"], kw["end"] = veh_se[v.id]
        return vroom.Vehicle(**kw)

    def _make_shipment(o, priority: int = 50, extra_skills: set | None = None):
        p_idx, d_idx = ord_pts[o.id]
        pw_start, pw_end = _pickup_window(o, early_sec, late_sec)
        pw_end = min(pw_end, day_end)
        excl = (1 if (o.id in fixed_pins or o.fleet in prm["auto_consent_fleets"])
                else EXCL_CAP if (prm["require_consent"] and o.pool_consent_at is None) else 1)
        if o.occupancy_min:
            su = td = o.occupancy_min * 30
            du = None
        else:
            su, td = _svc_split(o)
            du = _max_ride_upper(int(arr[p_idx][d_idx]), pw_end,
                                 prm.get("max_ride_factor", 0), prm.get("max_ride_grace_sec", 0))
        sk = set() if extra_skills is None else set(extra_skills)
        if o.id in all_pins:
            sk.add(PIN_SKILL_BASE + all_pins[o.id])
        pu = vroom.ShipmentStep(id=o.id, location=p_idx, default_service=su,
                                time_windows=[vroom.TimeWindow(pw_start, pw_end)])
        dk = dict(id=o.id + DELIVERY_OFFSET, location=d_idx, default_service=td)
        if du is not None:
            dk["time_windows"] = [vroom.TimeWindow(pw_start, du)]
        return pu, vroom.ShipmentStep(**dk), vroom.Amount([max(1, o.pax or 1), excl]), sk, priority

    # 篩出服務時段內的有效訂單
    out_of_service = 0
    valid_orders: list[Order] = []
    for o in orders:
        pw_start, _ = _pickup_window(o, early_sec, late_sec)
        if pw_start < day_start or pw_start > day_end:
            out_of_service += 1
        else:
            valid_orders.append(o)

    if not valid_orders and not ongoing:
        return {
            "service_date": service_date.isoformat(),
            "error": "該日無可排入的任務(訂單可能全在服務時段外或已完成)。",
            "orders_total": len(orders), "assigned": 0,
            "out_of_service": out_of_service,
            "skipped_no_coords": [o.id for o in skipped],
        }

    from app.services import tdx_traffic as _tdx_svc

    welfare_order_list = [o for o in valid_orders if _is_welfare(o)]
    normal_order_list  = [o for o in valid_orders if not _is_welfare(o)]

    # 規則②：抵達時間不得晚於預約時間 N 分鐘
    # 用系統設定 pickup_window_min（預設 30 分）作為排班容忍窗口
    # 10 分鐘規則用於結果標記（實際晚到 >10 分鐘的訂單加 dispatch_note）
    LATE_TOLERANCE_SEC = int(prm.get("pickup_window_min", 30) * 60)
    LATE_WARN_SEC      = 10 * 60   # 超過 10 分鐘標記為延誤

    def _greedy_sequential(
        veh_list: list,
        ord_list: list[Order],
        phase_name: str = "",
        initial_state: dict | None = None,
    ) -> tuple[dict, dict]:
        """貪婪序貫派遣：
        - 第一趟：從出車起點挑最近（行駛時間最短）且在鄰近地理區的訂單
        - 後續趟：從前一張訂單下車地點的鄰近地理區挑選（1層→2層→全區漸進）
        - 抵達時間不得晚於訂單預約時間 + LATE_TOLERANCE_SEC
        - initial_state: 跨 Phase 傳入車輛狀態 {vid: (pos_key, cur_time, district, seq)}
        - 回傳 (results_dict, final_state_dict)
        """
        results: dict[int, tuple] = {}
        available: set[int] = {o.id for o in ord_list}
        ord_by_id: dict[int, Order] = {o.id: o for o in ord_list}

        # 車輛狀態
        veh_pos_key:  dict[int, tuple[float, float] | None] = {}
        veh_time:     dict[int, int]   = {}
        veh_seq:      dict[int, int]   = {}
        veh_district: dict[int, str | None] = {}

        _margin = int(prm.get("driver_margin_sec", 0))
        _buf    = int(prm.get("completion_buffer_sec", 0))
        _early_sec = int(prm.get("pickup_early_min", 15) * 60)

        for v in veh_list:
            if initial_state and v.id in initial_state:
                # 繼承上一 Phase 的車輛狀態
                pos_key, cur_t, dist, seq = initial_state[v.id]
                veh_pos_key[v.id]  = pos_key
                veh_time[v.id]     = cur_t
                veh_district[v.id] = dist
                veh_seq[v.id]      = seq
            else:
                s = _first_coord((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
                if s is None:
                    continue
                rs, re = duty.get(v.id, (None, None))
                veh_pos_key[v.id]  = (round(s[0], 6), round(s[1], 6))
                veh_time[v.id]     = max(veh_day_start - _margin, rs or 0)
                veh_seq[v.id]      = 0
                veh_district[v.id] = _nearest_district(s[0], s[1])

        _midnight = datetime.combine(service_date, time(0), tzinfo=TW)

        def _pick_best(zone: set[str] | None, cur_idx: int, cur_time: int,
                       re_limit: int, tdx_f: float):
            """在指定地理區（None=全區）中找最佳下一單。
            評分策略：預約時間早的優先（先服務早的單），時間相近時以行駛時間短優先。
            """
            best_oid, best_score, best_arr, best_end = None, float("inf"), 0, 0
            for oid in available:
                o = ord_by_id[oid]
                # 地理區過濾
                if zone is not None:
                    o_dist = _nearest_district(o.pickup_lng, o.pickup_lat)
                    if o_dist and o_dist not in zone:
                        continue
                p_key = (round(o.pickup_lng, 6), round(o.pickup_lat, 6))
                p_idx = index.get(p_key)
                if p_idx is None:
                    continue
                base_t = int(arr[cur_idx][p_idx])
                if base_t >= UNROUTABLE:
                    continue
                # 用原始 OSRM 行駛時間做時間窗判斷（與 VROOM 行為一致）
                arrival = cur_time + base_t
                try:
                    o_dt   = o.pickup_time.astimezone(TW) if o.pickup_time.tzinfo else o.pickup_time
                    o_secs = _secs_of_day(o_dt.timetz())
                except Exception:
                    continue
                # 規則②：抵達時間不得晚於預約時間 + LATE_TOLERANCE_SEC
                if arrival > o_secs + LATE_TOLERANCE_SEC:
                    continue
                wait_dep = max(arrival, o_secs - _early_sec)
                su, td = _svc_split(o)
                d_key = (round(o.dropoff_lng, 6), round(o.dropoff_lat, 6))
                d_idx = index.get(d_key)
                eff_d   = int(arr[p_idx][d_idx]) if d_idx is not None else 1800
                svc_end = wait_dep + su + eff_d + td
                if svc_end > re_limit:
                    continue
                # 評分：預約時間優先（早的先），行駛時間次要
                score = o_secs * 100000 + base_t
                if score < best_score:
                    best_score, best_oid, best_arr, best_end = score, oid, wait_dep, svc_end
            return (best_oid, best_arr, best_end) if best_oid is not None else None

        progress = True
        while progress and available:
            progress = False
            for v in veh_list:
                if v.id not in veh_pos_key or veh_pos_key[v.id] is None:
                    continue
                cur_key = veh_pos_key[v.id]
                cur_idx = index.get(cur_key)
                if cur_idx is None:
                    continue
                cur_time = veh_time[v.id]
                cur_dist = veh_district[v.id]
                rs, re   = duty.get(v.id, (None, None))
                re_limit = min(veh_day_end + _buf, re) if re else veh_day_end + _buf
                if cur_time >= re_limit:
                    continue
                # TDX 係數（規則④）：用於 ETA 計算與延誤標記，但不縮小時間窗口
                # 使用原始 OSRM 時間做時間窗判斷（與 VROOM 一致），TDX 僅影響實際 ETA
                tdx_f = 1.0  # 時間窗判斷不套 TDX（避免早峰 0.48 讓所有訂單超窗）
                tdx_f_actual = _tdx_svc.get_time_factor_for_sec(cur_time)  # 實際 ETA 用

                # 漸進地理區：1層 → 2層 → 全區（規則①②）
                zone1    = ({cur_dist} | DISTRICT_NEIGHBORS.get(cur_dist, set())) if cur_dist else None
                zone2    = _expand_district_zone(cur_dist, 2) if cur_dist else None
                picked   = (_pick_best(zone1, cur_idx, cur_time, re_limit, tdx_f)
                            or _pick_best(zone2, cur_idx, cur_time, re_limit, tdx_f)
                            or _pick_best(None,  cur_idx, cur_time, re_limit, tdx_f))

                if picked is not None:
                    best_oid, best_arrival, best_svc_end = picked
                    o = ord_by_id[best_oid]
                    veh_seq[v.id] += 1
                    eta_dt = _midnight + timedelta(seconds=best_arrival)
                    # 計算實際相對於預約時間的延誤（供標記用）
                    try:
                        _o_dt   = o.pickup_time.astimezone(TW) if o.pickup_time.tzinfo else o.pickup_time
                        _o_secs = _secs_of_day(_o_dt.timetz())
                        _late   = max(0, best_arrival - _o_secs)
                    except Exception:
                        _late = 0
                    results[best_oid] = (v.id, eta_dt, veh_seq[v.id], _late)
                    available.discard(best_oid)
                    # 更新車輛狀態：移到下車地點
                    veh_pos_key[v.id]  = (round(o.dropoff_lng, 6), round(o.dropoff_lat, 6))
                    veh_time[v.id]     = best_svc_end
                    veh_district[v.id] = _nearest_district(o.dropoff_lng, o.dropoff_lat)
                    progress = True

        # 回傳最終車輛狀態（供下一 Phase 繼承）
        final_state = {
            v.id: (veh_pos_key.get(v.id), veh_time.get(v.id, 0),
                   veh_district.get(v.id), veh_seq.get(v.id, 0))
            for v in veh_list if v.id in veh_pos_key
        }
        log.info(f"[{phase_name}] 派遣 {len(results)} 趟")
        return results, final_state

    import pandas as pd

    # ── TDX 路況調整矩陣 ──────────────────────────────────────────────
    # 依當日訂單預約時間中位數選定時段係數，縮放 OSRM 行駛時間
    _all_hours = []
    for _o in valid_orders:
        try:
            _dt = _o.pickup_time.astimezone(TW) if _o.pickup_time.tzinfo else _o.pickup_time
            _all_hours.append(_dt.hour)
        except Exception:
            pass
    _median_sec = (sorted(_all_hours)[len(_all_hours) // 2] * 3600) if _all_hours else day_start
    _tdx_arr = _tdx_svc.scale_matrix_for_time(arr, _median_sec)
    _tdx_factor = _tdx_svc.get_time_factor_for_sec(_median_sec)
    log.info(f"TDX 路況：中位數時段={_median_sec//3600:02d}:xx 係數={_tdx_factor:.2f}")

    def _add_shipment(p_input, o, prio):
        """加入訂單 shipment（含地理技能 + 車型技能 + PIN 技能）。
        福祉訂單強制帶 skill {1}，確保一般車無法接福祉單。
        貪婪預釘訂單：縮緊時間窗強制 VROOM 排為該車第一趟。
        """
        pu, de, amt, sk, prio = _make_shipment(o, prio)
        # 福祉訂單：強制要求 skill {1}（一般車無此技能 → 硬性排除）
        if _is_welfare(o):
            sk.add(1)
        # 貪婪/固定釘定訂單已透過 PIN skill 鎖定特定車輛，無需再加地區限制
        if o.id not in all_pins:
            dist_sk = _order_district_skill(o.customer_region) if hasattr(o, "customer_region") else None
            if dist_sk is None and o.pickup_lng is not None:
                dist_sk = _order_district_skill(_nearest_district(o.pickup_lng, o.pickup_lat))
            if dist_sk is not None:
                sk.add(dist_sk)

        # 貪婪預釘訂單：縮緊時間窗 → 車輛最早抵達時間 ± 20 分鐘
        # 讓 VROOM 只能把這張單排在出車後立即執行（強制第一趟）
        if o.id in _greedy_pin_arrival:
            earliest = _greedy_pin_arrival[o.id]
            tight_win = vroom.TimeWindow(max(0, earliest - early_sec),
                                         earliest + 20 * 60)
            # 重建 pickup step（僅替換時間窗，其他不變）
            p_idx, _ = ord_pts[o.id]
            su, _ = _svc_split(o)
            pu = vroom.ShipmentStep(id=o.id, location=p_idx, default_service=su,
                                    time_windows=[tight_win])

        p_input.add_shipment(pu, de, amount=amt, skills=sk, priority=prio)

    def _make_veh(v, zone_restrict=True, cur_pos_district=None,
                  max_tasks_override=None, zone_levels=1,
                  cur_pos_idx=None, cur_depart_sec=None):
        """建立 VROOM 車輛物件。
        cur_pos_district: 以此行政區為基準更新地理技能（迭代輪次）。
        cur_pos_idx:      上一輪實際結束的 point index，覆寫車輛起點。
        cur_depart_sec:   上一輪實際離開下車點的秒數，作為本輪時間窗開始。
        max_tasks_override: 覆寫 MAX_TASKS（每輪 1 趟 = 2）。
        zone_levels: 鄰近區展開層數（0=僅同區, 1=1層, 2=2層）。
        """
        rs, re = duty.get(v.id, (None, None))
        ws = max(veh_day_start, rs) if rs is not None else veh_day_start
        we = min(veh_day_end, re) if re is not None else veh_day_end
        # cur_depart_sec 保留供未來「最短空車等待」優化使用，
        # 時間窗維持原班表範圍，讓 VROOM 依矩陣距離自行決定是否來得及
        sk = {1} if v.type == "welfare" else set()
        if v.id in lock_vehicles:
            sk.add(LOCK_SKILL_BASE + v.id)
        if v.id in all_pin_vehicle_ids:
            sk.add(PIN_SKILL_BASE + v.id)
        if zone_restrict:
            base_dist = cur_pos_district
            if base_dist is None:
                sk |= _vehicle_zone_skills(v)
            else:
                zone = _expand_district_zone(base_dist, zone_levels)
                sk |= {DISTRICT_SKILL_BASE + _DIST_IDX[d] for d in zone if d in _DIST_IDX}
        else:
            sk |= {DISTRICT_SKILL_BASE + i for i in range(len(NTPC_DISTRICTS))}
        mt = max_tasks_override if max_tasks_override is not None else MAX_TASKS
        kw = dict(id=v.id, profile="car",
                  capacity=[max(1, v.seats or 1), EXCL_CAP],
                  skills=sk,
                  time_window=vroom.TimeWindow(ws, we),
                  max_travel_time=prm["max_work_sec"],
                  max_tasks=mt,
                  costs=veh_costs)
        # 起點：優先用上一輪實際下車位置，否則用 home 設定
        if cur_pos_idx is not None:
            kw["start"] = cur_pos_idx
            # end 維持原 home end（收車終點不變）
            if v.id in veh_se:
                kw["end"] = veh_se[v.id][1]
        elif v.id in veh_se:
            kw["start"], kw["end"] = veh_se[v.id]
        return vroom.Vehicle(**kw)

    def _last_dropoff_info(vid, routes_df):
        """取該車最後一趟 delivery 的 (point_index, arrival_sec, district)。
        供下一輪把車輛起點與時間窗開始設為實際結束位置。"""
        if routes_df is None or routes_df.empty:
            return None, None, None
        vdf = routes_df[(routes_df["vehicle_id"] == vid) & (routes_df["type"] == "delivery")]
        if vdf.empty:
            return None, None, None
        row = vdf.iloc[-1]
        loc_idx = int(row["location_index"])
        if loc_idx >= len(points):
            return None, None, None
        # arrival + service_time = 車輛實際離開下車點的時間
        arrival_sec = int(row.get("arrival", 0))
        svc_sec     = int(row.get("service", 0))
        depart_sec  = arrival_sec + svc_sec
        lng, lat = points[loc_idx]
        district = _nearest_district(lng, lat)
        return loc_idx, depart_sec, district

    def _solve(veh_list, ord_list, supplement=None, zone_restrict=True,
               last_routes=None, use_tdx=True, max_tasks_override=None,
               zone_levels=1, tdx_ref_sec=None):
        """單次 VROOM 求解。
        supplement:    補充訂單（低優先度 30，不帶車型技能需求）。
        last_routes:   取各車最後下車位置/時間/行政區（第二趟起銜接用）。
        zone_levels:   地理技能展開層數（0=同區, 1=1層鄰近, 2=2層）。
        max_tasks_override: 覆寫每車最大任務數（2 = 每輪限 1 趟）。
        tdx_ref_sec:   TDX 矩陣參考秒數（None=用全天預算矩陣）。
        """
        if not veh_list or (not ord_list and not supplement):
            return set(), pd.DataFrame(), 0
        p = vroom.Input()
        # 修法三：若有指定時段，動態選 TDX 矩陣
        if use_tdx and tdx_ref_sec is not None:
            round_arr = _tdx_svc.scale_matrix_for_time(arr, tdx_ref_sec)
        else:
            round_arr = _tdx_arr if use_tdx else arr
        p.set_durations_matrix("car", round_arr)
        for v in veh_list:
            # 修法一：取上一輪實際下車位置 + 離開時間
            if last_routes is not None:
                pos_idx, depart_sec, dist = _last_dropoff_info(v.id, last_routes)
            else:
                pos_idx, depart_sec, dist = None, None, None
            p.add_vehicle(_make_veh(v, zone_restrict=zone_restrict,
                                    cur_pos_district=dist,
                                    max_tasks_override=max_tasks_override,
                                    zone_levels=zone_levels,
                                    cur_pos_idx=pos_idx,
                                    cur_depart_sec=depart_sec))
        for o in (ord_list or []):
            prio = 80 if o.id in fixed_pins else (65 if o.id in greedy_pins else 50)
            _add_shipment(p, o, prio)
        for o in (supplement or []):
            pu, de, amt, sk, _ = _make_shipment(o, 30)
            sk.discard(1)
            dist_sk = _order_district_skill(o.customer_region) if hasattr(o, "customer_region") else None
            if dist_sk is None and o.pickup_lng is not None:
                dist_sk = _order_district_skill(_nearest_district(o.pickup_lng, o.pickup_lat))
            if dist_sk is not None:
                sk.add(dist_sk)
            p.add_shipment(pu, de, amount=amt, skills=sk, priority=30)
        for o in ongoing:
            if o.assigned_vehicle_id in {v.id for v in veh_list}:
                excl = EXCL_CAP if (prm["require_consent"] and o.pool_consent_at is None) else 1
                sk_o = {LOCK_SKILL_BASE + o.assigned_vehicle_id}
                if _is_welfare(o):
                    sk_o.add(1)
                p.add_job(vroom.Job(id=o.id, location=ongoing_pts[o.id],
                                   delivery=vroom.Amount([max(1, o.pax or 1), excl]),
                                   skills=sk_o, default_service=_svc_split(o)[1], priority=100))
        s = p.solve(exploration_level=5, nb_threads=4)
        assigned = {int(r["id"]) for _, r in s.routes.iterrows()
                    if r["type"] == "pickup" and r["id"] == r["id"]}
        return assigned, s.routes, int(s.summary.duration)

    def _parse_phase_results(routes_df, exclude_ids, base_midnight):
        """從 VROOM routes DataFrame 解析 {order_id: (vid, eta, seq)} 結果。"""
        seq_map: dict[int, int] = {}
        results: dict[int, tuple] = {}
        for _, row in (routes_df if not routes_df.empty else pd.DataFrame()).iterrows():
            if row["type"] == "pickup" and not (row["id"] != row["id"]):
                oid = int(row["id"])
                if oid not in exclude_ids:
                    vid = int(row["vehicle_id"])
                    eta = base_midnight + timedelta(seconds=int(row["arrival"]))
                    seq = seq_map.get(vid, 0) + 1
                    seq_map[vid] = seq
                    results[oid] = (vid, eta, seq)
        return results

    _midnight_dt = datetime.combine(service_date, time(0), tzinfo=TW)

    # ── 第一趟：全車全單，max_tasks=2（每車只派一趟），出車起點鄰近區 ──
    # 貪婪預釘 + 縮緊時間窗確保第一趟接近出車起點
    p1_assigned, _routes_p1, _dur_p1 = _solve(
        vehicles, valid_orders,
        zone_restrict=True, use_tdx=True,
        max_tasks_override=2,          # 每車第一輪只排 1 趟
        zone_levels=1,                 # 出車起點 + 1 層鄰近區
    )
    if _routes_p1 is None:
        _routes_p1 = pd.DataFrame()
    p1_results = _parse_phase_results(_routes_p1, set(), _midnight_dt)

    # ── 第二趟起：迭代 VROOM，以前一趟下車地點行政區更新技能 ──────────
    # 規則：下一趟上車點必須在前一趟下車點行政區 + 鄰近區（不超過 1 個行政區）
    # 漸進放寬：1層 → 2層 → 全區（乾輪累計才放寬）
    _combined_routes = _routes_p1.copy() if not _routes_p1.empty else pd.DataFrame()
    _assigned_all: set[int] = set(p1_assigned)
    _iter_results: dict[int, tuple] = {}
    _dry = 0

    for _rnd in range(40):                       # 最多 40 輪
        _remaining_iter = [o for o in valid_orders if o.id not in _assigned_all]
        if not _remaining_iter:
            break
        # 修法二：同區優先 0層 → 乾1輪放寬1層 → 乾2輪最多2層（不再全區開放）
        _zlvl = 0 if _dry == 0 else (1 if _dry == 1 else 2)
        # 修法三：用本輪剩餘訂單的中位上車時段算 TDX
        _rnd_hours = []
        for _o in _remaining_iter:
            try:
                _dt = _o.pickup_time.astimezone(TW) if _o.pickup_time.tzinfo else _o.pickup_time
                _rnd_hours.append(_dt.hour)
            except Exception:
                pass
        _rnd_ref_sec = (sorted(_rnd_hours)[len(_rnd_hours) // 2] * 3600) if _rnd_hours else None
        _rnd_assigned, _rnd_routes, _ = _solve(
            vehicles, _remaining_iter,
            zone_restrict=True,
            last_routes=_combined_routes,
            use_tdx=True,
            max_tasks_override=2,      # 每輪每車 1 趟
            zone_levels=_zlvl,
            tdx_ref_sec=_rnd_ref_sec,
        )
        if not _rnd_assigned:
            _dry += 1
            if _dry >= 3:
                break
            continue
        _dry = 0
        _assigned_all |= _rnd_assigned
        _iter_results.update(_parse_phase_results(_rnd_routes, set(), _midnight_dt))
        if not _rnd_routes.empty:
            _combined_routes = pd.concat([_combined_routes, _rnd_routes],
                                         ignore_index=True)
        log.info(f"迭代第 {_rnd+1} 輪：派 {len(_rnd_assigned)} 趟，"
                 f"累計 {len(_assigned_all)} / {len(valid_orders)}")

    # ── 第三輪：福祉車補接剩餘一般單（全區開放）────────────────────────
    _welfare_vehs = [v for v in vehicles if v.type == "welfare"]
    _normal_unassigned = [o for o in normal_order_list if o.id not in _assigned_all]
    _p3_assign: dict[int, tuple] = {}
    if _normal_unassigned and _welfare_vehs:
        _, _routes_p3, _ = _solve(
            _welfare_vehs, [], supplement=_normal_unassigned,
            zone_restrict=False, use_tdx=True
        )
        _p3_assign = _parse_phase_results(
            _routes_p3 if not _routes_p3.empty else pd.DataFrame(),
            _assigned_all, _midnight_dt
        )

    # 合併所有結果，整理為寫回格式
    _p2_assign = _iter_results          # 迭代輪次視為 Phase 2
    _p2_count  = len(_iter_results)
    _p3_count  = len(_p3_assign)
    p2_results = _p2_assign
    p3_results = _p3_assign

    # 建立 _FakeSol 供後續寫回使用（與原有寫回邏輯相容）
    class _FakeSol:
        def __init__(self, routes, dur=0):
            self.routes = routes
            class _summary: duration = dur
            self.summary = _summary()
    sol = _FakeSol(_routes_p1, _dur_p1)

    # 從 Phase 1 routes 解析 ETA 結果
    _p1_midnight = datetime.combine(service_date, time(0), tzinfo=TW)
    _p1_seq: dict[int, int] = {}
    p1_results: dict[int, tuple] = {}
    for _, _r1 in (_routes_p1 if not _routes_p1.empty else pd.DataFrame()).iterrows():
        if _r1["type"] == "pickup" and not (_r1["id"] != _r1["id"]):
            _oid1 = int(_r1["id"])
            _vid1 = int(_r1["vehicle_id"])
            _eta1 = _p1_midnight + timedelta(seconds=int(_r1["arrival"]))
            _sq1 = _p1_seq.get(_vid1, 0) + 1
            _p1_seq[_vid1] = _sq1
            p1_results[_oid1] = (_vid1, _eta1, _sq1, 0)

    # p2_results / p3_results for return dict compatibility
    p2_results = _p2_assign
    p3_results = _p3_assign

    # 合併所有派遣結果
    all_results: dict = {**p1_results, **_p2_assign, **_p3_assign}

    # 5) 寫回結果
    for o in orders:
        o.assigned_vehicle_id = None
        o.dispatch_seq = None
        o.eta = None
        o.status = "imported"
        o.support_fleet = None
        o.dispatch_note = None

    midnight = datetime.combine(service_date, time(0), tzinfo=TW)
    by_id = {o.id: o for o in orders}
    routes_report: dict[int, list[dict]] = {}
    pickup_seq: dict[int, int] = {}
    stop_seq: dict[int, int] = {}

    db.query(RouteStop).filter(RouteStop.service_date == service_date).delete()

    for oid, result_tuple in sorted(all_results.items(),
                                    key=lambda x: (x[1][0], x[1][2])):
        vid, eta_dt, seq = result_tuple[0], result_tuple[1], result_tuple[2]
        late_sec = result_tuple[3] if len(result_tuple) > 3 else 0
        o = by_id.get(oid)
        if not o:
            continue
        o.assigned_vehicle_id = vid
        o.dispatch_seq = seq
        o.eta = eta_dt
        o.status = "scheduled"
        # 實際晚到超過 10 分鐘 → 標記
        if late_sec > LATE_WARN_SEC:
            o.dispatch_note = f"晚到 {late_sec//60} 分鐘"
        addr = o.pickup_address
        arr_hhmm = eta_dt.strftime("%H:%M")

        routes_report.setdefault(vid, []).append(
            {"seq": seq, "order_id": oid, "type": "上車",
             "eta": arr_hhmm, "addr": addr}
        )
        # 下車站（ETA 估算：上車 + 直達行程時間）
        try:
            p_key = (round(o.pickup_lng, 6), round(o.pickup_lat, 6))
            d_key = (round(o.dropoff_lng, 6), round(o.dropoff_lat, 6))
            p_idx = index.get(p_key)
            d_idx = index.get(d_key)
            if p_idx is not None and d_idx is not None:
                base_tt = int(arr[p_idx][d_idx])
                su, td = _svc_split(o)
                dropoff_secs = int(eta_dt.timestamp()) - int(midnight.timestamp()) + su + base_tt + td
            else:
                dropoff_secs = int(eta_dt.timestamp()) - int(midnight.timestamp()) + 1800
            dropoff_eta = midnight + timedelta(seconds=dropoff_secs)
            dropoff_hhmm = dropoff_eta.strftime("%H:%M")
        except Exception:
            dropoff_eta = eta_dt
            dropoff_hhmm = "??:??"

        routes_report[vid].append(
            {"order_id": oid, "type": "下車",
             "eta": dropoff_hhmm, "addr": o.dropoff_address}
        )

        # RouteStop 上車
        sseq_p = stop_seq.get(vid, 0) + 1
        stop_seq[vid] = sseq_p
        db.add(RouteStop(
            service_date=service_date, vehicle_id=vid, seq=sseq_p, kind="pickup",
            order_id=oid,
            lng=o.pickup_lng, lat=o.pickup_lat,
            eta=eta_dt, address=addr,
        ))
        # RouteStop 下車
        sseq_d = stop_seq.get(vid, 0) + 1
        stop_seq[vid] = sseq_d
        db.add(RouteStop(
            service_date=service_date, vehicle_id=vid, seq=sseq_d, kind="delivery",
            order_id=oid,
            lng=o.dropoff_lng, lat=o.dropoff_lat,
            eta=dropoff_eta,
            address=o.dropoff_address,
        ))

    db.commit()

    assigned_ids = {o.id for o in orders if o.assigned_vehicle_id is not None}
    unassigned = [o.id for o in orders if o.id not in assigned_ids]

    # 第二階段(他隊支援 / 隔離補救):第一階段分群後仍有未派 → 當日回退統一池重排,
    # 由公司其他車隊餘裕運能承接;統一池的指派數 ≥ 分群,保證不因分群漏單。
    #  - cross_fleet_support 開:預設行為(本車行優先→他隊支援),並把支援單留痕。
    #  - 舊 fleet_isolation + fallback:維持原補救語意。
    # _isolation_override=None(outer)才觸發,避免無限遞迴。
    trigger_second = (
        outer_pass and apply_group and unassigned
        and (support_on or (legacy_iso and prm.get("fleet_isolation_fallback")))
    )
    if trigger_second:
        short_fleets = {by_id[oid].fleet for oid in unassigned if oid in by_id}  # 運能不足的車行
        res = run_dispatch(db, service_date, _isolation_override=False)   # 統一池重排(權威結果)
        supported = _label_cross_fleet_support(db, service_date, short_fleets)   # 標記他隊支援 + 原因
        res["isolation_fallback"] = True
        res["cross_fleet_support"] = support_on
        res["supported"] = supported
        res["supported_count"] = len(supported)
        return res

    # 寫入未派記錄(供「未派分析」頁查詢)
    has_welfare_veh = any(v.type == "welfare" for v in vehicles)
    db.query(UnassignedRecord).filter(UnassignedRecord.service_date == service_date).delete()
    for oid in unassigned:
        o = by_id.get(oid)
        if not o:
            continue
        h = o.pickup_time.astimezone(TW).hour if o.pickup_time else 12
        if h < day_start // 3600 or h >= day_end // 3600:
            code, detail = "out_of_hours", "上車時間在服務時段外(06:00–18:00)"
        elif o.pickup_lng is None or o.dropoff_lng is None:
            code, detail = "no_coords", "缺少地址座標,無法地理編碼"
        elif o.vehicle_type == "welfare" and not has_welfare_veh:
            code, detail = "no_welfare", "需福祉車但當日無福祉車出勤"
        elif o.vehicle_type == "welfare":
            code, detail = "infeasible", "福祉車運能不足或時間窗衝突"
        else:
            code, detail = "infeasible", "車隊運能不足或時間窗衝突(需增派或重排)"
        db.add(UnassignedRecord(
            service_date=service_date,
            fleet=o.fleet,
            order_id=o.id,
            source_order_no=o.source_order_no,
            reason_code=code,
            reason_detail=detail,
        ))
    db.commit()

    return {
        "service_date": service_date.isoformat(),
        "provider": m["provider"],
        "vehicles_used": len(routes_report),
        "orders_total": len(orders),
        "assigned": len(assigned_ids),
        "unassigned": unassigned,
        "ongoing_locked": len(ongoing),
        "fixed_pinned": len(fixed_pins),
        "greedy_pinned": len(greedy_pins),
        "phase1_welfare": len(p1_results),
        "round2_mixed_assigned": _p2_count,
        "round3_welfare_supplement": _p3_count,
        "phase2_normal": len(p2_results),
        "phase3_supplement": len(p3_results),
        "out_of_service": out_of_service,
        "skipped_no_coords": [o.id for o in skipped],
        "routes": routes_report,
        "shared_pool_orders": [o.id for o in orders
                                if (o.pickup_address or "").strip() in shared_addrs],
    }
