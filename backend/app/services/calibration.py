"""每趟作業時間 / 區域速度 的歷史校準。

問題:派遣模型原本用全域固定「每趟 40 分作業」(前置 20 + 後置 20),
對金山這類短程密集接駁過重(實測人工每趟僅 ~20 分),導致用車高估、未派偏多。

做法(全數據驅動,不靠直覺):
- 取 dispatch_history 中**同車同日、背靠背(連續上車間隔 ≤ 45 分)**的趟對。
  連續間隔 gap = A車程 + A後置 + 空車(A下車→B上車)+ B前置。
  扣掉 A車程與「空車」(以兩點直線距離估,避免與 VROOM 矩陣的調度時間重複計算)→
  得「每趟作業(後置+前置)」的實證值。
- 依「車行 × 是否福祉單」取中位數;樣本不足者退回全域(fleet='*')。
- 另算各車行「隱含車速(km/h)」供區域速度稽核(山區/都會差異)。

純讀 dispatch_history、不呼叫 OSRM,CI 可離線跑分析函式。
"""
from __future__ import annotations

import math
from datetime import timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dispatch_history import DispatchHistory
from app.models.fleet_calibration import FleetCalibration

TW = timezone(timedelta(hours=8))
SERVED = "已轉至正式單"
BACK_TO_BACK_MIN = 45          # 連續間隔 ≤ 此值視為「背靠背」(無閒置等待)
DEADHEAD_KMH = 22.0            # 估空車時間用的平均車速
MIN_SAMPLES = 30               # 校準所需最少趟對;不足則退全域
SERVICE_FLOOR_MIN = 12         # 每趟作業下限(分)
SERVICE_CAP_MIN = 45           # 每趟作業上限(分)
DEFAULT_SERVICE_MIN = 20       # 全域樣本也不足時的保底值(對應 10+10)


def _km(lng1, lat1, lng2, lat2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _clamp_service_min(v: float) -> int:
    return int(round(max(SERVICE_FLOOR_MIN, min(SERVICE_CAP_MIN, v)) * 60))


def analyze(db: Session) -> dict:
    """從歷史反推每趟作業時間(分)與隱含車速,依車行 × 福祉/一般 聚合。

    回傳 {fleets: {fleet: {...}}, global: {...}}。各 {...} 含 normal_min/welfare_min/
    samples 與 speed_kmh。純函式產物,不寫庫。
    """
    rows = list(db.scalars(
        select(DispatchHistory).where(
            DispatchHistory.status == SERVED,
            DispatchHistory.plate.like("R%"),
            DispatchHistory.pickup_time.is_not(None),
        )
    ).all())

    # 分組 (plate, date) 內依上車時間排序,算背靠背趟對的「每趟作業」
    by_vehicleday: dict[tuple, list] = {}
    for r in rows:
        by_vehicleday.setdefault((r.plate, r.service_date), []).append(r)

    # 收集:fleet -> welfare? -> [service_min];以及 fleet -> [speed_kmh]
    serv: dict[str, dict[bool, list[float]]] = {}
    speed: dict[str, list[float]] = {}

    def _welfare(r) -> bool:
        return bool(r.vehicle_type_req and "福祉" in r.vehicle_type_req)

    for trips in by_vehicleday.values():
        trips.sort(key=lambda r: r.pickup_time)
        for i in range(len(trips) - 1):
            a, b = trips[i], trips[i + 1]
            gap_min = (b.pickup_time - a.pickup_time).total_seconds() / 60
            if not (0 < gap_min <= BACK_TO_BACK_MIN):
                continue
            drive_min = a.est_minutes or 0
            # 空車(A下車 → B上車)直線估時,避免與矩陣調度時間重複
            dead_min = 0.0
            if None not in (a.dropoff_lng, a.dropoff_lat, b.pickup_lng, b.pickup_lat):
                dead_min = _km(a.dropoff_lng, a.dropoff_lat, b.pickup_lng, b.pickup_lat) / DEADHEAD_KMH * 60
            service = gap_min - drive_min - dead_min   # ≈ A後置 + B前置 = 每趟作業
            if service <= 0:
                continue
            f = a.fleet or "?"
            serv.setdefault(f, {True: [], False: []})[_welfare(a)].append(service)
        # 隱含車速(各趟)
        for r in trips:
            km = (r.distance_m or 0) / 1000
            mins = r.est_minutes or 0
            if km > 0.5 and mins > 1:
                speed.setdefault(r.fleet or "?", []).append(km / (mins / 60))

    # 全域(所有 fleet 合併)
    all_norm = [x for d in serv.values() for x in d[False]]
    all_welf = [x for d in serv.values() for x in d[True]]
    all_speed = [x for xs in speed.values() for x in xs]
    g_norm = _median(all_norm) if all_norm else DEFAULT_SERVICE_MIN
    g_welf = _median(all_welf) if all_welf else g_norm

    def pack(norm_list, welf_list, speed_list, g_n, g_w):
        n_norm, n_welf = len(norm_list), len(welf_list)
        return {
            "normal_min": round(_median(norm_list), 1) if n_norm >= MIN_SAMPLES else round(g_n, 1),
            "welfare_min": round(_median(welf_list), 1) if n_welf >= MIN_SAMPLES else round(g_w, 1),
            "normal_samples": n_norm,
            "welfare_samples": n_welf,
            "speed_kmh": round(_median(speed_list), 1) if speed_list else None,
            "speed_samples": len(speed_list),
            "calibrated": (n_norm + n_welf) >= MIN_SAMPLES,
        }

    fleets = {}
    for f in sorted(set(serv) | set(speed)):
        fleets[f] = pack(serv.get(f, {False: []})[False], serv.get(f, {True: []})[True],
                         speed.get(f, []), g_norm, g_welf)
    g_speed = round(_median(all_speed), 1) if all_speed else None
    return {
        "fleets": fleets,
        "global": {
            "normal_min": round(g_norm, 1), "welfare_min": round(g_welf, 1),
            "normal_samples": len(all_norm), "welfare_samples": len(all_welf),
            "speed_kmh": g_speed, "speed_samples": len(all_speed), "calibrated": True,
        },
        "params": {
            "back_to_back_min": BACK_TO_BACK_MIN, "min_samples": MIN_SAMPLES,
            "floor_min": SERVICE_FLOOR_MIN, "cap_min": SERVICE_CAP_MIN,
        },
    }


def apply(db: Session) -> dict:
    """把 analyze() 結果寫入 fleet_calibration(含全域 '*' 列)。回傳寫入摘要。"""
    a = analyze(db)
    g = a["global"]
    g_speed = g["speed_kmh"] or 0
    written = 0

    def upsert(fleet, normal_min, welfare_min, samples, speed_kmh):
        nonlocal written
        row = db.get(FleetCalibration, fleet)
        if row is None:
            row = FleetCalibration(fleet=fleet)
            db.add(row)
        row.service_normal_sec = _clamp_service_min(normal_min)
        row.service_welfare_sec = _clamp_service_min(welfare_min)
        # 速度係數:該區隱含車速相對全域;>1 表示該區較慢 → 車程乘上去(目前資料近 1.0)
        row.speed_factor = round(g_speed / speed_kmh, 3) if (speed_kmh and g_speed) else 1.0
        row.samples = samples
        written += 1

    upsert("*", g["normal_min"], g["welfare_min"],
           g["normal_samples"] + g["welfare_samples"], g_speed)
    for f, v in a["fleets"].items():
        if v["calibrated"]:
            upsert(f, v["normal_min"], v["welfare_min"],
                   v["normal_samples"] + v["welfare_samples"], v["speed_kmh"] or g_speed)
    db.commit()
    return {"written": written, "global": a["global"], "fleets": a["fleets"]}


# --- 模型查詢介面:派遣 / 對比讀此取每趟作業秒數與速度係數 ---

def service_map(db: Session) -> dict:
    """回傳 {fleet: (normal_sec, welfare_sec, speed_factor)} + '*' 全域。
    無校準資料時回空 dict(呼叫端退回設定頁的全域 trip_setup/teardown)。"""
    out = {}
    for r in db.scalars(select(FleetCalibration)).all():
        out[r.fleet] = (r.service_normal_sec, r.service_welfare_sec, r.speed_factor or 1.0)
    return out


def effective_service_sec(svc: dict, fleet: str | None, welfare: bool,
                          default_sec: int) -> int:
    """依 (車行, 福祉) 取每趟作業秒數;車行無校準→全域'*';皆無→ default_sec。"""
    row = svc.get(fleet or "") or svc.get("*")
    if row is None:
        return default_sec
    return row[1] if welfare else row[0]
