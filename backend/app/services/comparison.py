"""人工 vs 自動(VROOM)對比引擎。

對某車行某日:取「已成行」訂單 + 人工當天實際用到的車 → 跑 VROOM(OSRM 矩陣)
→ 比較用車數 / 行駛 / 可行性。唯讀(不寫排班),結果存 dispatch_comparison。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import vroom
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.dispatch_comparison import DispatchComparison
from app.models.dispatch_history import DispatchHistory
from app.models.order import Order
from app.models.unassigned_record import UnassignedRecord
from app.models.vehicle import Vehicle
from app.services import calibration as calib_svc
from app.services import fixed_route_match
from app.services import matrix as matrix_svc
from app.services import settings as settings_svc

DELIVERY_OFFSET = 1_000_000
UNROUTABLE = 9_999_999
SERVED = "已轉至正式單"
TW = timezone(timedelta(hours=8))   # 台灣時區:上車時間以 +08 牆鐘換算當日秒數

# --- 司機工時 / 共乘 營運規則 ---
TRIP_SETUP = 1200          # 上車前 20 分(秒)
TRIP_TEARDOWN = 1200       # 下車後 20 分(秒)→ 每趟前後共 40 分工時
DAY_START = 6 * 3600       # 接送服務時段起 06:00(最早可上車)
DAY_END = 18 * 3600        # 接送服務時段迄 18:00(最晚可上車)
COMPLETION_BUFFER = 2 * 3600   # 車輛可延後完成 18:00 前上車的趟次(營運至 20:00)
MAX_WORK_SEC = 8 * 3600    # 每車每日工時上限 8h(VROOM 以行車+服務時間近似)
EXCL_CAP = 100             # 「不共乘」維度容量;未同意共乘者佔滿 → 獨佔整車
RIDE_FACTOR = 1.8          # 最長乘車時間 = 直達車程 × 此倍率 + 緩衝(固定方法學,與即時派遣預設一致)
RIDE_GRACE_SEC = 1800      # 乘車上限固定加項 30 分
MIN_MAX_RIDE_SEC = 2400    # 乘車上限下限 40 分(短程也容一次併車繞路)


def _max_ride_upper(direct_sec: int, pw_end: int) -> int | None:
    """下車時間窗上限 = 上車窗末 + max(下限, 直達車程×倍率 + 緩衝);不可路由則不設限。
    限制乘客在車上最長時間,避免 VROOM 為省車把長程下車延到收車前。"""
    if direct_sec >= UNROUTABLE:
        return None
    return pw_end + max(MIN_MAX_RIDE_SEC, int(direct_sec * RIDE_FACTOR) + RIDE_GRACE_SEC)


def _secs(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _secs_tw(dt) -> int:
    """上車 datetime 換算為台灣當日秒數(資料庫存 UTC,需轉 +08)。"""
    local = dt.astimezone(TW) if dt.tzinfo else dt
    return local.hour * 3600 + local.minute * 60 + local.second


def _hm(dt) -> str | None:
    """datetime → 'HH:MM'(台灣時區牆鐘)。"""
    if dt is None:
        return None
    local = dt.astimezone(TW) if getattr(dt, "tzinfo", None) else dt
    return f"{local.hour:02d}:{local.minute:02d}"


def _hm_secs(sec: int) -> str:
    """當日秒數(VROOM arrival,自午夜起算)→ 'HH:MM'。"""
    sec = max(0, int(sec))
    return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}"


GEO_OUTLIER_KM = 40.0   # 上/下車離當日營運區中位點超過此距離 → 疑似地理編碼錯誤


def _km(lng1, lat1, lng2, lat2) -> float:
    """兩點 haversine 距離(公里)。"""
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _median_point(orders) -> tuple[float, float]:
    """當日所有上/下車點的中位經緯度(對少數錯誤座標穩健,作為營運區中心)。"""
    lngs, lats = [], []
    for o in orders:
        for lng, lat in ((o.pickup_lng, o.pickup_lat), (o.dropoff_lng, o.dropoff_lat)):
            if lng is not None and lat is not None:
                lngs.append(lng)
                lats.append(lat)
    if not lngs:
        return (0.0, 0.0)
    lngs.sort()
    lats.sort()
    n = len(lngs)
    return (lngs[n // 2], lats[n // 2])


def _classify_unassigned(o, secs: int, direct_sec: int, has_welfare: bool,
                         centroid: tuple[float, float], saturated: bool) -> tuple[str, str]:
    """把未派訂單歸到「可行動」原因碼。"""
    hh, mm = secs // 3600, (secs % 3600) // 60
    if secs < DAY_START or secs > DAY_END:
        return "out_of_hours", f"預約上車 {hh:02d}:{mm:02d} 落在服務時段(06:00–18:00)之外"
    if o.vehicle_type == "welfare" and not has_welfare:
        return "no_welfare", "需福祉車,但當日該車行無福祉車可服務"
    if direct_sec >= UNROUTABLE:
        return "unroutable", "上/下車點無法由路網規劃路徑(地址或座標可能有誤)"
    far = max(_km(o.pickup_lng, o.pickup_lat, *centroid),
              _km(o.dropoff_lng, o.dropoff_lat, *centroid)) if centroid != (0.0, 0.0) else 0
    if far >= GEO_OUTLIER_KM:
        return ("suspect_geocode",
                f"上/下車座標離當日營運區約 {far:.0f} 公里,疑似地理編碼錯誤(地址可能被編到他縣市,請校正座標)")
    if saturated:
        return "fleet_saturated", "當日該車行所有車輛皆已投入且滿載,需增派車輛才排得進此趟"
    return ("solver_margin",
            "車隊仍有閒置/餘力屬求解邊際(常見於固定趟釘定車在緊上車窗下趕不到起點);"
            "放寬上車時間窗、或校正既定區塊起點為路線起點,多可排入")


def compare_day(db: Session, fleet: str, service_date: date, window_min: int | None = None,
                return_plan: bool = False, return_stops: bool = False) -> dict | None:
    """回傳對比指標 dict;當日無成行單或無車則回 None。

    return_stops=True 時額外回傳 stops=[{vehicle_id,plate,seq,kind,order_id,lng,lat,eta,
    occupancy,is_support}...](自動派遣每車每停靠點,供持久化)。

    window_min=None 時讀系統參數 pickup_window_min(預設窗)。
    作業時間另乘系統參數 service_time_factor(省車鬆緊主旋鈕,不竄改校準真值)。

    return_plan=True 時額外回傳 plan={vehicle_id: [order_id,...](依路線順序)},
    供「系統派遣口卡」呈現系統最佳化後每車每趟(批次不傳此旗標,零額外負擔)。
    """
    if window_min is None:
        window_min = settings_svc.get(db, "pickup_window_min", 30)
    svc_factor = float(settings_svc.get(db, "service_time_factor", 1.0) or 1.0)
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

    # 既定區塊(固定趟):occupancy_min 有值 → 釘到 assigned_vehicle_id。
    # 確保被釘車輛在集合內;給每筆固定趟一個唯一 skill,只有該車具此 skill → 強制釘車,
    # 各固定趟各釘各車(去/回程同車),故不會互相併車(回應「A、B 不能綁在一起」)。
    fixed_orders = [o for o in orders if o.occupancy_min and o.assigned_vehicle_id]
    have_ids = {v.id for v in vehicles}
    for vid in {o.assigned_vehicle_id for o in fixed_orders} - have_ids:
        v = db.get(Vehicle, vid)
        if v is not None:
            vehicles.append(v)
    pin_skill: dict[int, int] = {}      # order_id -> 唯一釘車 skill
    veh_pins: dict[int, set] = {}        # vehicle_id -> {釘車 skills}
    for k, fo in enumerate(fixed_orders):
        sk = 1000 + k
        pin_skill[fo.id] = sk
        veh_pins.setdefault(fo.assigned_vehicle_id, set()).add(sk)
    # 既定區塊車輛的出車起點 = 其「最早既定區塊」的上車點(校車司機從路線起點發車,非中央 depot),
    # 避免緊上車窗下釘定車從遠處 depot 趕不到而未派。
    block_start: dict[int, tuple[float, float]] = {}
    for fo in sorted(fixed_orders, key=lambda o: o.pickup_time):
        if fo.assigned_vehicle_id not in block_start and fo.pickup_lng is not None:
            block_start[fo.assigned_vehicle_id] = (fo.pickup_lng, fo.pickup_lat)

    # 乘客姓名匹配固定行程 → 視同固定趟:釘指定司機的車(簡單釘車,正常作業、可與該司機其他單共乘;
    # 非既定區塊者不設佔用時間)。與即時派遣一致,讓比對也認得「有指定司機的固定趟」。
    order_ids = {o.id for o in orders}
    k2 = len(fixed_orders)
    for oid, vid in fixed_route_match.match_for_date(db, service_date)["pins"].items():
        if oid not in order_ids or oid in pin_skill:
            continue   # 非本車行本日單、或已是既定區塊(occupancy)→ 略過
        pin_skill[oid] = 1000 + k2
        veh_pins.setdefault(vid, set()).add(1000 + k2)
        k2 += 1
    have_ids = {v.id for v in vehicles}
    for vid in set(veh_pins) - have_ids:
        v = db.get(Vehicle, vid)
        if v is not None:
            vehicles.append(v)

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
        # 既定區塊車:起點=最早既定區塊上車點(校車從路線起點發車);否則用出車起點/depot
        s = block_start.get(v.id) or _first((v.start_lng, v.start_lat), (v.depot_lng, v.depot_lat))
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
    # 區域速度係數(歷史校準):該車行較慢→車程乘大;近 1.0 為無作用
    svc = calib_svc.service_map(db)
    sf = (svc.get(fleet) or svc.get("*") or (0, 0, 1.0))[2]
    if sf and sf != 1.0:
        arr = np.minimum((arr.astype(np.float64) * sf).round(), UNROUTABLE).astype(np.uint32)

    def _svc_split(o) -> tuple[int, int]:
        """該訂單每趟作業秒數 → (前置, 後置);依車行×福祉歷史校準,無則退 40 分。"""
        sec = calib_svc.effective_service_sec(
            svc, o.fleet, o.vehicle_type == "welfare", TRIP_SETUP + TRIP_TEARDOWN)
        return sec // 2, sec - sec // 2

    problem = vroom.Input()
    problem.set_durations_matrix("car", arr)
    for v in vehicles:
        # 彈性工時:不綁固定班別,僅受 06:00–18:00 服務時段 + 8h 工時上限約束
        # capacity = [座位, 不共乘維度];共乘規則用第二維度表達
        kw = dict(id=v.id, profile="car",
                  capacity=[max(1, v.seats or 1), EXCL_CAP],
                  skills=({1} if v.type == "welfare" else set()) | veh_pins.get(v.id, set()),
                  # 營運迄延後到 20:00,以完成 18:00 前上車的趟次(上車仍限 06–18)
                  time_window=vroom.TimeWindow(DAY_START, DAY_END + COMPLETION_BUFFER),
                  max_travel_time=MAX_WORK_SEC)
        if v.id in veh_se:
            kw["start"], kw["end"] = veh_se[v.id]
        problem.add_vehicle(vroom.Vehicle(**kw))
    for o in orders:
        s = _secs_tw(o.pickup_time)
        if s < DAY_START or s > DAY_END:
            continue   # 上車落在服務時段外 → 不納入(於未派明細標 out_of_hours)
        p_idx, d_idx = ord_pts[o.id]
        welfare = o.vehicle_type == "welfare"   # 原則4:只看車型,不以 need_wheelchair 判定
        pw_end = min(s + window_min * 60, DAY_END)
        if o.id in pin_skill and o.occupancy_min:
            # 既定區塊:整趟佔用時間當服務時長、釘指定車(唯一 skill)、不設最長乘車上限;
            # excl=1 讓同車去/回程與空檔正常單可共存(不互併由唯一 skill 各釘各車保證)。
            total = (o.occupancy_min or 0) * 60
            setup_sec, teardown_sec = total // 2, total - total // 2
            excl = 1
            deliv_upper = None
            o_skills = ({1} if welfare else set()) | {pin_skill[o.id]}
        elif o.id in pin_skill:
            # 姓名匹配固定行程(固定趟)→ 釘指定司機車;固定趟等級凌駕共乘同意 → 強制可併(原則1),
            # 與該司機其他趟自然併車(非既定區塊獨佔)。
            excl = 1
            setup_sec, teardown_sec = _svc_split(o)
            if svc_factor != 1.0:
                setup_sec = int(setup_sec * svc_factor)
                teardown_sec = int(teardown_sec * svc_factor)
            deliv_upper = _max_ride_upper(int(arr[p_idx][d_idx]), pw_end)
            o_skills = ({1} if welfare else set()) | {pin_skill[o.id]}
        else:
            # 共乘需同意:以 pool_consent_at 有值為準,未同意者第二維度佔滿 EXCL_CAP → 獨佔整車
            excl = 1 if o.pool_consent_at is not None else EXCL_CAP
            setup_sec, teardown_sec = _svc_split(o)   # 每趟作業:歷史校準(車行×福祉)
            if svc_factor != 1.0:                     # 省車鬆緊主旋鈕(係數,不改校準真值)
                setup_sec = int(setup_sec * svc_factor)
                teardown_sec = int(teardown_sec * svc_factor)
            deliv_upper = _max_ride_upper(int(arr[p_idx][d_idx]), pw_end)   # 限制最長乘車時間
            o_skills = {1} if welfare else set()
        deliv_kw = dict(id=o.id + DELIVERY_OFFSET, location=d_idx, default_service=teardown_sec)
        if deliv_upper is not None:
            deliv_kw["time_windows"] = [vroom.TimeWindow(s, deliv_upper)]
        problem.add_shipment(
            vroom.ShipmentStep(id=o.id, location=p_idx, default_service=setup_sec,
                               time_windows=[vroom.TimeWindow(s, pw_end)]),
            vroom.ShipmentStep(**deliv_kw),
            amount=vroom.Amount([max(1, o.pax or 1), excl]),
            skills=o_skills,
            priority=100,  # 人工當天已全數服務 → 強制 VROOM 盡量服務,再看需幾台車
        )

    sol = problem.solve(exploration_level=5, nb_threads=4)
    df = sol.routes
    vroom_vehicles = int(df[df["type"] == "pickup"]["vehicle_id"].nunique()) if len(df) else 0
    drive_sec = float(sol.summary.duration)
    # 注意:sol.summary.unassigned 計的是「任務數」(每單上車+下車算 2),會 2× 灌水;
    # 實際未派訂單數以下方 unassigned_detail 的長度為準(見 vroom_unassigned)。

    # 未派訂單明細 + 可行動原因(供「未派分析」與行控回饋)
    assigned_ids = set(int(i) for i in df[df["type"] == "pickup"]["id"].tolist()) if len(df) else set()
    has_welfare = any(v.type == "welfare" for v in vehicles)
    centroid = _median_point(orders)
    saturated = vroom_vehicles >= len(vehicles)   # 車隊是否已全數投入(無閒置車)
    unassigned_detail = []
    for o in orders:
        if o.id in assigned_ids:
            continue
        s = _secs_tw(o.pickup_time)
        p_idx, d_idx = ord_pts[o.id]
        code, detail = _classify_unassigned(
            o, s, int(arr[p_idx][d_idx]), has_welfare, centroid, saturated)
        unassigned_detail.append({
            "order_id": o.id, "source_order_no": o.source_order_no,
            "reason_code": code, "reason_detail": detail,
        })

    human_vehicles = len(plates)
    hd = db.execute(
        select(func.coalesce(func.sum(DispatchHistory.distance_m), 0),
               func.coalesce(func.sum(DispatchHistory.est_minutes), 0))
        .where(DispatchHistory.fleet == fleet, DispatchHistory.service_date == service_date,
               DispatchHistory.status == SERVED)
    ).one()

    plan = None
    if return_plan and len(df):
        plan = {}
        for _, step in df.iterrows():
            if step["type"] == "pickup":
                plan.setdefault(int(step["vehicle_id"]), []).append(int(step["id"]))

    stops = None
    if return_stops and len(df):
        stops = []
        omap = {o.id: o for o in orders}
        vmap = {v.id: v for v in vehicles}
        midnight = datetime.combine(service_date, time(0), tzinfo=TW)
        has_wait = "waiting_time" in df.columns
        seq_by_vid: dict[int, int] = {}
        load_by_vid: dict[int, int] = {}
        for _, step in df.iterrows():
            typ = step["type"]
            if typ not in ("pickup", "delivery"):
                continue
            vid = int(step["vehicle_id"])
            arr = int(step["arrival"]) if step["arrival"] == step["arrival"] else 0
            wait = int(step["waiting_time"]) if (has_wait and step["waiting_time"] == step["waiting_time"]) else 0
            if typ == "pickup":
                oid = int(step["id"]); o = omap.get(oid)
                lng, lat = (o.pickup_lng, o.pickup_lat) if o else (None, None)
                load_by_vid[vid] = load_by_vid.get(vid, 0) + (o.pax or 1 if o else 0)
            else:
                oid = int(step["id"]) - DELIVERY_OFFSET; o = omap.get(oid)
                lng, lat = (o.dropoff_lng, o.dropoff_lat) if o else (None, None)
                load_by_vid[vid] = load_by_vid.get(vid, 0) - (o.pax or 1 if o else 0)
            seq = seq_by_vid.get(vid, 0) + 1; seq_by_vid[vid] = seq
            v = vmap.get(vid)
            stops.append({
                "vehicle_id": vid, "plate": v.plate if v else None,
                "seq": seq, "kind": typ, "order_id": oid,
                "lng": lng, "lat": lat, "eta": midnight + timedelta(seconds=arr + wait),
                "occupancy": load_by_vid[vid],
                "is_support": bool(v and o and (v.home_fleet or "") != (o.fleet or "")),
            })

    return {
        "fleet": fleet, "service_date": service_date, "window_min": window_min,
        "n_orders": len(orders),
        "human_vehicles": human_vehicles,
        "vroom_vehicles": vroom_vehicles,
        "vroom_unassigned": len(unassigned_detail),   # 實際未派訂單數(非 VROOM 任務數)
        "saved_vehicles": human_vehicles - vroom_vehicles,
        "human_distance_m": float(hd[0]), "human_minutes": float(hd[1]),
        "vroom_drive_sec": drive_sec,
        "unassigned_detail": unassigned_detail,
        "plan": plan,
        "stops": stops,
    }


def _persist_unassigned(db: Session, fleet: str, service_date: date, window_min: int,
                        detail: list[dict]) -> int:
    """把某日未派明細寫入 unassigned_record,並關聯人工派遣的車/駕駛。"""
    if not detail:
        return 0
    nos = [d["source_order_no"] for d in detail if d["source_order_no"]]
    human = {}
    if nos:
        for h in db.scalars(select(DispatchHistory).where(
                DispatchHistory.fleet == fleet, DispatchHistory.service_date == service_date,
                DispatchHistory.source_order_no.in_(nos))).all():
            human[h.source_order_no] = h
    for d in detail:
        h = human.get(d["source_order_no"])
        db.add(UnassignedRecord(
            service_date=service_date, fleet=fleet,
            order_id=d["order_id"], source_order_no=d["source_order_no"],
            reason_code=d["reason_code"], reason_detail=d["reason_detail"],
            window_min=window_min,
            human_plate=h.plate if h else None,
            human_driver=h.driver_name if h else None,
        ))
    return len(detail)


def run_batch(db: Session, window_min: int | None = None, progress=None) -> dict:
    """對所有(車行×有成行單的日子)做對比,結果寫入 dispatch_comparison + unassigned_record。

    window_min=None 時讀系統參數 pickup_window_min;作業時間另乘 service_time_factor。
    """
    if window_min is None:
        window_min = settings_svc.get(db, "pickup_window_min", 30)
    db.query(DispatchComparison).delete()
    db.query(UnassignedRecord).delete()
    db.commit()

    combos = db.execute(
        select(Order.fleet, Order.service_date)
        .where(Order.status == "done")
        .group_by(Order.fleet, Order.service_date)
        .order_by(Order.fleet, Order.service_date)
    ).all()

    done = 0
    skipped = 0
    n_unassigned = 0
    for fleet, sd in combos:
        try:
            r = compare_day(db, fleet, sd, window_min)
        except Exception:  # noqa: BLE001
            r = None
        if r is None:
            skipped += 1
            continue
        detail = r.pop("unassigned_detail", [])
        r.pop("plan", None)   # plan 為 return_plan 用,非 DispatchComparison 欄位
        db.add(DispatchComparison(**r))
        n_unassigned += _persist_unassigned(db, fleet, sd, window_min, detail)
        done += 1
        if done % 25 == 0:
            db.commit()
            if progress:
                progress(done, len(combos))
    db.commit()
    return {"combos": len(combos), "compared": done, "skipped": skipped,
            "unassigned_records": n_unassigned}


def persist_day(db: Session, service_date: date, window_min: int | None = None) -> dict:
    """把某日『自動派遣結果』全數落地(標準流程步驟①,只清/重寫該日,勿動其他日):
    對各車行跑 compare_day(=自動派遣)→ 寫入彙總 dispatch_comparison + 未派 unassigned_record
    + **每車每停靠點明細 auto_dispatch_stop**。這是「每次自動派遣結果都存進 DB」的入口。"""
    from app.models.auto_dispatch_stop import AutoDispatchStop
    if window_min is None:
        window_min = settings_svc.get(db, "pickup_window_min", 30)
    run_at = datetime.now(TW)
    for model in (DispatchComparison, UnassignedRecord, AutoDispatchStop):
        db.query(model).filter(model.service_date == service_date).delete()
    db.commit()

    fleets = [f for (f,) in db.execute(
        select(Order.fleet).where(Order.service_date == service_date, Order.status == "done")
        .group_by(Order.fleet).order_by(Order.fleet)).all() if f]
    res = {"service_date": service_date.isoformat(), "fleets": 0, "stops": 0,
           "unassigned": 0, "human_vehicles": 0, "vroom_vehicles": 0}
    for fl in fleets:
        r = compare_day(db, fl, service_date, window_min, return_stops=True)
        if not r:
            continue
        stops = r.pop("stops", None) or []
        detail = r.pop("unassigned_detail", [])
        r.pop("plan", None)
        res["human_vehicles"] += r["human_vehicles"]
        res["vroom_vehicles"] += r["vroom_vehicles"]
        db.add(DispatchComparison(**r))
        res["unassigned"] += _persist_unassigned(db, fl, service_date, window_min, detail)
        for s in stops:
            db.add(AutoDispatchStop(service_date=service_date, fleet=fl,
                                    run_at=run_at, window_min=window_min, **s))
        res["fleets"] += 1
        res["stops"] += len(stops)
    db.commit()
    res["saved_vehicles"] = res["human_vehicles"] - res["vroom_vehicles"]
    return res


def compare_day_by_vehicle(db: Session, fleet: str, service_date: date,
                           window_min: int = 30) -> dict | None:
    """逐車對比:同一天、同一組實體車輛,左=人工實際派遣、右=VROOM 自動派遣。

    人工用車從 dispatch_history 的車牌建出 → VROOM 在同一車隊池上重排,
    因此每台車(以車牌對應)可左右並排,標出「哪幾趟換了車」。
    另回傳每車當日總行駛里程與工作時間,供成本/工時比較。

    回傳 None 表示當日無成行單或查無人工用車。
    """
    orders = list(db.scalars(
        select(Order).where(
            Order.fleet == fleet, Order.service_date == service_date,
            Order.status == "done",
            Order.pickup_lng.is_not(None), Order.dropoff_lng.is_not(None),
        ).order_by(Order.id)
    ).all())
    if not orders:
        return None
    ord_by_id = {o.id: o for o in orders}
    oid_by_no = {o.source_order_no: o.id for o in orders if o.source_order_no}

    plates = [p for (p,) in db.execute(
        select(DispatchHistory.plate.distinct()).where(
            DispatchHistory.fleet == fleet, DispatchHistory.service_date == service_date,
            DispatchHistory.status == SERVED, DispatchHistory.plate.like("R%"),
        )
    ).all() if p]
    vehicles = list(db.scalars(select(Vehicle).where(Vehicle.plate.in_(plates))).all()) if plates else []
    if not vehicles:
        return None
    plate_by_vid = {v.id: v.plate for v in vehicles}

    points: list[tuple[float, float]] = []
    index: dict[tuple[float, float], int] = {}

    def pt(lng, lat) -> int:
        k = (round(lng, 6), round(lat, 6))
        if k not in index:
            index[k] = len(points)
            points.append(k)
        return index[k]

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
    dur = np.array(
        [[int(round(c)) if c is not None else UNROUTABLE for c in row] for row in m["durations"]],
        dtype=np.int64,
    )
    dists = m.get("distances")
    dist = None
    if dists:
        dist = np.array([[float(c) if c is not None else 0.0 for c in row] for row in dists], dtype=float)

    # 區域速度係數 + 每趟作業(歷史校準,車行×福祉)
    svc = calib_svc.service_map(db)
    sf = (svc.get(fleet) or svc.get("*") or (0, 0, 1.0))[2]
    if sf and sf != 1.0:
        dur = np.minimum((dur.astype(np.float64) * sf).round(), UNROUTABLE).astype(np.int64)
    svc_by_oid = {
        o.id: calib_svc.effective_service_sec(svc, o.fleet, o.vehicle_type == "welfare",
                                              TRIP_SETUP + TRIP_TEARDOWN)
        for o in orders
    }

    problem = vroom.Input()
    problem.set_durations_matrix("car", dur.astype(np.uint32))
    for v in vehicles:
        kw = dict(id=v.id, profile="car",
                  capacity=[max(1, v.seats or 1), EXCL_CAP],
                  skills={1} if v.type == "welfare" else set(),
                  time_window=vroom.TimeWindow(DAY_START, DAY_END + COMPLETION_BUFFER),
                  max_travel_time=MAX_WORK_SEC)
        if v.id in veh_se:
            kw["start"], kw["end"] = veh_se[v.id]
        problem.add_vehicle(vroom.Vehicle(**kw))
    for o in orders:
        s = _secs_tw(o.pickup_time)
        if s < DAY_START or s > DAY_END:
            continue
        p_idx, d_idx = ord_pts[o.id]
        welfare = o.vehicle_type == "welfare"
        excl = 1 if o.pool_consent_at is not None else EXCL_CAP   # 共乘需同意留痕
        sec = svc_by_oid[o.id]
        setup_sec, teardown_sec = sec // 2, sec - sec // 2
        pw_end = min(s + window_min * 60, DAY_END)
        deliv_upper = _max_ride_upper(int(dur[p_idx][d_idx]), pw_end)   # 限制最長乘車時間
        deliv_kw = dict(id=o.id + DELIVERY_OFFSET, location=d_idx, default_service=teardown_sec)
        if deliv_upper is not None:
            deliv_kw["time_windows"] = [vroom.TimeWindow(s, deliv_upper)]
        problem.add_shipment(
            vroom.ShipmentStep(id=o.id, location=p_idx, default_service=setup_sec,
                               time_windows=[vroom.TimeWindow(s, pw_end)]),
            vroom.ShipmentStep(**deliv_kw),
            amount=vroom.Amount([max(1, o.pax or 1), excl]),
            skills={1} if welfare else set(),
            priority=100,
        )

    sol = problem.solve(exploration_level=5, nb_threads=4)
    df = sol.routes

    # 還原每車路徑(位置序)+ 服務趟次順序
    seq_by_vid: dict[int, list[int]] = {}
    picks_by_vid: dict[int, list[int]] = {}
    stops_by_vid: dict[int, list[dict]] = {}   # 真實停靠序(交錯上/下車)+ 到點時刻
    if len(df):
        has_wait = "waiting_time" in df.columns
        for _, step in df.iterrows():
            vid = int(step["vehicle_id"])
            typ = step["type"]
            # 到點時刻 = arrival + waiting(時間窗等待):上下車「實際發生」時刻,
            # 非車輛提早到達時刻(否則早到等窗會誤顯示成提早上車、虛增在車時間)
            arrival = int(step["arrival"]) if step["arrival"] == step["arrival"] else 0
            wait = int(step["waiting_time"]) if (has_wait and step["waiting_time"] == step["waiting_time"]) else 0
            sec = arrival + wait
            if typ == "start":
                seq_by_vid.setdefault(vid, []).append(veh_se.get(vid, (None, None))[0])
            elif typ == "pickup":
                oid = int(step["id"])
                seq_by_vid.setdefault(vid, []).append(ord_pts[oid][0])
                picks_by_vid.setdefault(vid, []).append(oid)
                stops_by_vid.setdefault(vid, []).append({"kind": "pickup", "oid": oid, "sec": sec})
            elif typ == "delivery":
                oid = int(step["id"]) - DELIVERY_OFFSET
                seq_by_vid.setdefault(vid, []).append(ord_pts[oid][1])
                stops_by_vid.setdefault(vid, []).append({"kind": "delivery", "oid": oid, "sec": sec})
            elif typ == "end":
                seq_by_vid.setdefault(vid, []).append(veh_se.get(vid, (None, None))[1])

    # 自動:訂單 → 車牌
    auto_plate_by_no: dict[str, str] = {}
    for vid, picks in picks_by_vid.items():
        plate = plate_by_vid.get(vid)
        for oid in picks:
            no = ord_by_id[oid].source_order_no
            if no:
                auto_plate_by_no[no] = plate
    assigned_auto_ids = {oid for picks in picks_by_vid.values() for oid in picks}
    has_welfare = any(v.type == "welfare" for v in vehicles)
    centroid = _median_point(orders)
    saturated = len(picks_by_vid) >= len(vehicles)
    auto_unassigned = []
    for o in orders:
        if o.id in assigned_auto_ids:
            continue
        p_idx, d_idx = ord_pts[o.id]
        code, detail = _classify_unassigned(
            o, _secs_tw(o.pickup_time), int(dur[p_idx][d_idx]), has_welfare, centroid, saturated)
        auto_unassigned.append({
            "order_id": o.id, "source_order_no": o.source_order_no, "pickup_hm": _hm(o.pickup_time),
            "passenger": o.passenger_name,
            "pickup_addr": o.pickup_address, "dropoff_addr": o.dropoff_address,
            "reason_code": code, "reason_detail": detail,
        })

    # 人工:每車牌的趟次(dispatch_history)
    hist = list(db.scalars(
        select(DispatchHistory).where(
            DispatchHistory.fleet == fleet, DispatchHistory.service_date == service_date,
            DispatchHistory.status == SERVED, DispatchHistory.plate.in_(plates),
        ).order_by(DispatchHistory.pickup_time)
    ).all())
    human_by_plate: dict[str, list] = {}
    human_plate_by_no: dict[str, str] = {}
    driver_by_plate: dict[str, str] = {}
    for h in hist:
        human_by_plate.setdefault(h.plate, []).append(h)
        if h.source_order_no:
            human_plate_by_no[h.source_order_no] = h.plate
        if h.driver_name and h.plate not in driver_by_plate:
            driver_by_plate[h.plate] = h.driver_name

    def _route_metrics(locs: list[int | None]) -> tuple[int, float]:
        """沿位置序加總行駛秒數與公尺(含調度空車段);None 視為斷點。"""
        drive_sec = 0
        dist_m = 0.0
        prev = None
        for loc in locs:
            if loc is None:
                prev = None
                continue
            if prev is not None:
                leg = int(dur[prev][loc])
                drive_sec += leg if leg < UNROUTABLE else 0
                if dist is not None:
                    dist_m += float(dist[prev][loc])
            prev = loc
        return drive_sec, dist_m

    veh_rows = []
    for v in vehicles:
        plate = v.plate
        vs, ve = veh_se.get(v.id, (None, None))
        # --- 人工:趟次(依上車時間)+ 同方法學的路徑里程/工時 ---
        hlist = human_by_plate.get(plate, [])
        h_orders = []
        h_loaded_m = h_rec_min = 0.0
        h_service_sec = 0
        h_locs: list[int | None] = [vs]
        for h in hlist:
            dm = h.distance_m or 0
            mn = h.est_minutes or 0
            h_loaded_m += dm
            h_rec_min += mn
            oid = oid_by_no.get(h.source_order_no)
            if oid is not None:
                h_locs.extend(ord_pts[oid])
                h_service_sec += svc_by_oid[oid]
            else:
                h_service_sec += calib_svc.effective_service_sec(
                    svc, fleet, bool(h.vehicle_type_req and "福祉" in h.vehicle_type_req),
                    TRIP_SETUP + TRIP_TEARDOWN)
            h_orders.append({
                "no": h.source_order_no, "pickup_hm": _hm(h.pickup_time),
                "passenger": ord_by_id[oid].passenger_name if oid is not None else None,
                "pickup_addr": h.pickup_address, "dropoff_addr": h.dropoff_address,
                "distance_km": round(dm / 1000, 1), "minutes": round(mn),
                "moved": auto_plate_by_no.get(h.source_order_no) != plate,
            })
        h_locs.append(ve)
        h_drive_sec, h_dist_m = _route_metrics(h_locs)

        # --- 自動:VROOM 趟次 + 路徑里程/工時 ---
        picks = picks_by_vid.get(v.id, [])
        a_orders = []
        for seq, oid in enumerate(picks, 1):
            o = ord_by_id[oid]
            a_orders.append({
                "no": o.source_order_no, "order_id": oid, "seq": seq,
                "pickup_hm": _hm(o.pickup_time), "passenger": o.passenger_name,
                "pickup_addr": o.pickup_address, "dropoff_addr": o.dropoff_address,
                "moved": human_plate_by_no.get(o.source_order_no) != plate,
            })
        a_drive_sec, a_dist_m = _route_metrics(seq_by_vid.get(v.id, []))
        a_service_sec = sum(svc_by_oid[oid] for oid in picks)
        # 真實停靠序(交錯上/下車)+ 到點時刻 + 在車人數 → 讓共乘一目了然
        a_stops = []
        onboard = 0
        for st in stops_by_vid.get(v.id, []):
            o = ord_by_id[st["oid"]]
            up = st["kind"] == "pickup"
            onboard += (o.pax or 1) if up else -(o.pax or 1)
            a_stops.append({
                "kind": "上車" if up else "下車",
                "eta": _hm_secs(st["sec"]),
                "passenger": o.passenger_name,
                "addr": o.pickup_address if up else o.dropoff_address,
                "onboard": max(0, onboard),
                "moved": human_plate_by_no.get(o.source_order_no) != plate,
            })

        veh_rows.append({
            "plate": plate,
            "driver": driver_by_plate.get(plate),
            "type": v.type,
            "seats": v.seats,
            "human": {
                "n": len(h_orders),
                "distance_km": round(h_dist_m / 1000, 1) if dist is not None else None,
                "drive_min": round(h_drive_sec / 60),
                "work_min": round((h_drive_sec + h_service_sec) / 60),
                "loaded_km": round(h_loaded_m / 1000, 1),   # 來源檔記載之載客里程(參考)
                "rec_min": round(h_rec_min),                # 來源檔記載之行駛分鐘(參考)
                "orders": h_orders,
            },
            "auto": {
                "n": len(a_orders),
                "distance_km": round(a_dist_m / 1000, 1) if dist is not None else None,
                "drive_min": round(a_drive_sec / 60),
                "work_min": round((a_drive_sec + a_service_sec) / 60),
                "orders": a_orders,
                "stops": a_stops,
            },
            "human_used": len(h_orders) > 0,
            "auto_used": len(a_orders) > 0,
        })
    veh_rows.sort(key=lambda r: r["plate"] or "")

    totals = {
        "human": {
            "vehicles": sum(1 for r in veh_rows if r["human_used"]),
            "distance_km": round(sum((r["human"]["distance_km"] or 0) for r in veh_rows), 1) if dist is not None else None,
            "work_min": sum(r["human"]["work_min"] for r in veh_rows),
            "drive_min": sum(r["human"]["drive_min"] for r in veh_rows),
        },
        "auto": {
            "vehicles": sum(1 for r in veh_rows if r["auto_used"]),
            "distance_km": round(sum((r["auto"]["distance_km"] or 0) for r in veh_rows), 1) if dist is not None else None,
            "work_min": sum(r["auto"]["work_min"] for r in veh_rows),
            "drive_min": sum(r["auto"]["drive_min"] for r in veh_rows),
        },
    }
    return {
        "fleet": fleet, "service_date": service_date.isoformat(), "window_min": window_min,
        "provider": m.get("provider"), "distance_available": dist is not None,
        "n_orders": len(orders),
        "vehicles": veh_rows, "auto_unassigned": auto_unassigned, "totals": totals,
    }


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
