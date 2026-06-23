"""固定行程「既定骨架」+ 衝突偵測(階段一,唯讀分析,不改派遣)。

理念:固定行程由指定司機執行 = 既定承諾,不參與最佳化。本服務把每位指定司機當天的
固定趟次排成時間骨架,計算每趟的佔用窗(上車前置 → 行程 → 下車後置),並偵測:
  - overlap   :同司機兩趟時間重疊 → 單一車輛無法分身(就是 6/22 那種超載)。
  - transfer  :下一趟上車早於「前一趟下車 + 接駁車程」→ 銜接不及。
同時計算每位司機的「可接單空檔」,供後續(階段二)塞彈性單參考。

純讀:用 fixed_route_match 的釘選 + 訂單座標 + OSRM 車程;不寫任何資料、不影響現行派遣。
"""
from __future__ import annotations

from datetime import date, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fixed_route import FixedRoute
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import fixed_route_match, geocode as geocode_svc, settings as settings_svc
from app.services import matrix as matrix_svc

TW = timezone(timedelta(hours=8))
DAY_START = 6 * 3600
DAY_END = 18 * 3600
TRANSFER_SLACK = 300   # 銜接容許誤差 5 分


def effective_occupancy_min(db: Session, fr: FixedRoute) -> int:
    """固定趟整趟佔用時間(分)。

    逐條規則的 occupancy_min 優先(行控於維護頁設定);未設則以參數設定估算:
    max(佔用下限, OSRM 頭尾直達車程 + 多站緩衝)。
    """
    P = settings_svc.fixed_route_params(db)
    if fr.occupancy_min:
        return fr.occupancy_min
    occ = P["min_occupancy_min"]
    if fr.pickup_address and fr.dropoff_address:
        p = geocode_svc.geocode(db, fr.pickup_address)
        d = geocode_svc.geocode(db, fr.dropoff_address)
        if p.found and d.found:
            try:
                direct = matrix_svc.build_matrix(
                    [(p.lng, p.lat), (d.lng, d.lat)])["durations"][0][1] or 0
                occ = max(P["min_occupancy_min"], round(direct / 60) + P["multistop_buffer_min"])
            except Exception:  # noqa: BLE001
                pass
    return occ


def resolve_params(db: Session, fr: FixedRoute) -> dict:
    """回傳固定行程「生效參數」:逐條值優先,缺項回退參數設定的預設。

    供維護頁顯示生效值、與「產生當日既定區塊」共用同一套覆寫→預設邏輯。
    """
    return {
        "occupancy_min": effective_occupancy_min(db, fr),
        "occupancy_source": "route" if fr.occupancy_min else "settings_estimate",
        "allow_pool": bool(fr.allow_pool),     # 預設 False(對應 fixed_route_default_no_pool)
        "pax": fr.pax or 1,
        "vehicle_type": fr.vehicle_type or "normal",
        "wheelchair": fr.wheelchair or 0,
        "plate": fr.plate,
        "driver_name": fr.driver_name,
        "pickup_address": fr.pickup_address,
        "dropoff_address": fr.dropoff_address,
        "start_time": fr.start_time,
    }


def _secs(dt) -> int:
    t = dt.astimezone(TW)
    return t.hour * 3600 + t.minute * 60 + t.second


def _durations(points: list[tuple[float, float]]) -> list[list[float]]:
    """車程矩陣;OSRM 不可用(如 CI 無 OSRM)時退回 haversine 估算,確保不中斷。"""
    try:
        return matrix_svc.build_matrix(points)["durations"]
    except Exception:  # noqa: BLE001
        return matrix_svc._haversine_matrix(points)["durations"]


def analyze(db: Session, service_date: date) -> dict:
    prm = settings_svc.dispatch_params(db)
    setup, teardown = prm["setup_sec"], prm["teardown_sec"]

    match = fixed_route_match.match_for_date(db, service_date)
    pins = match["pins"]                       # order_id -> vehicle_id
    if not pins:
        return {"service_date": service_date.isoformat(), "drivers": [],
                "conflicts": [], "summary": {"fixed_trips": 0, "drivers": 0,
                                             "conflict_count": 0, "idle_vehicle_hours": 0.0}}

    orders = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_(list(pins)))).all()}
    veh = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(set(pins.values())))).all()}
    label_of = {it["order_id"]: it["label"] for it in match["items"]}

    # 依車輛(司機)分組
    by_veh: dict[int, list[Order]] = {}
    for oid, vid in pins.items():
        o = orders.get(oid)
        if o and o.pickup_time and o.pickup_lng is not None and o.dropoff_lng is not None:
            by_veh.setdefault(vid, []).append(o)

    drivers_out, conflicts, idle_hours = [], [], 0.0

    for vid, trips in sorted(by_veh.items()):
        trips.sort(key=lambda o: o.pickup_time)
        # 一次建該車所有點(上+下)的車程矩陣
        pts, idx = [], {}
        for o in trips:
            idx[(o.id, "p")] = len(pts); pts.append((o.pickup_lng, o.pickup_lat))
            idx[(o.id, "d")] = len(pts); pts.append((o.dropoff_lng, o.dropoff_lat))
        dur = _durations(pts)

        blocks = []
        for o in trips:
            ps = _secs(o.pickup_time)
            travel = int(dur[idx[(o.id, "p")]][idx[(o.id, "d")]])
            ds = ps + travel
            blocks.append({
                "order_id": o.id, "label": label_of.get(o.id, ""),
                "passenger": o.passenger_name, "pax": o.pax or 1,
                "pickup_sec": ps, "dropoff_sec": ds, "travel_sec": travel,
                "occ_start": ps - setup, "occ_end": ds + teardown,
                "time": o.pickup_time.astimezone(TW).strftime("%H:%M"),
                "dropoff_lng": o.dropoff_lng, "dropoff_lat": o.dropoff_lat,
                "pickup_lng": o.pickup_lng, "pickup_lat": o.pickup_lat,
            })

        # 相鄰趟衝突偵測
        veh_conflicts = []
        for a, b in zip(blocks, blocks[1:]):
            if b["occ_start"] < a["occ_end"]:
                # 時間重疊:除非同終點可併車(座位夠)
                same_dest = (abs(a["dropoff_lng"] - b["dropoff_lng"]) < 1e-4
                             and abs(a["dropoff_lat"] - b["dropoff_lat"]) < 1e-4)
                poolable = same_dest and (a["pax"] + b["pax"] <= (veh.get(vid).seats or 4))
                veh_conflicts.append({
                    "type": "overlap", "vehicle_id": vid,
                    "plate": veh.get(vid).plate if veh.get(vid) else None,
                    "a": a["label"], "a_time": a["time"], "b": b["label"], "b_time": b["time"],
                    "poolable_hint": poolable,
                    "note": "同時段、同終點,可評估共乘併車" if poolable else "時間重疊,單車無法分身,需備援/改派",
                })
            else:
                # 銜接可行性:b 上車是否來得及(a 下車 + 接駁車程)
                tr = _durations(
                    [(a["dropoff_lng"], a["dropoff_lat"]), (b["pickup_lng"], b["pickup_lat"])]
                )[0][1]
                if b["pickup_sec"] < a["dropoff_sec"] + teardown + int(tr) - TRANSFER_SLACK:
                    veh_conflicts.append({
                        "type": "transfer", "vehicle_id": vid,
                        "plate": veh.get(vid).plate if veh.get(vid) else None,
                        "a": a["label"], "a_time": a["time"], "b": b["label"], "b_time": b["time"],
                        "poolable_hint": False,
                        "note": f"銜接不及:{a['time']} 下車後到 {b['time']} 上車點車程不足",
                    })
        conflicts.extend(veh_conflicts)

        # 可接單空檔(服務時段內、扣固定趟佔用,合併重疊後估算)
        busy = 0
        merged = []
        for blk in sorted(blocks, key=lambda x: x["occ_start"]):
            s, e = max(blk["occ_start"], DAY_START), min(blk["occ_end"], DAY_END)
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        busy = sum(e - s for s, e in merged)
        idle = max(0, (DAY_END - DAY_START) - busy)
        idle_hours += idle / 3600

        drivers_out.append({
            "vehicle_id": vid,
            "plate": veh.get(vid).plate if veh.get(vid) else None,
            "trips": len(blocks),
            "first": blocks[0]["time"], "last": blocks[-1]["time"],
            "busy_hours": round(busy / 3600, 1),
            "idle_hours": round(idle / 3600, 1),
            "has_conflict": bool(veh_conflicts),
            "blocks": [{"label": b["label"], "time": b["time"], "pax": b["pax"]} for b in blocks],
        })

    drivers_out.sort(key=lambda d: (not d["has_conflict"], -d["idle_hours"]))
    return {
        "service_date": service_date.isoformat(),
        "drivers": drivers_out,
        "conflicts": conflicts,
        "summary": {
            "fixed_trips": len(pins),
            "drivers": len(by_veh),
            "conflict_count": len(conflicts),
            "conflicted_drivers": sum(1 for d in drivers_out if d["has_conflict"]),
            "idle_vehicle_hours": round(idle_hours, 1),
        },
    }
