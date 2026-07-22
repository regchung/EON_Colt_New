"""未排班訂單自動指派。

演算法（Greedy，依上車時間排序）：
  1. 篩車種：welfare 訂單僅考慮 welfare 車。
  2. 篩時間：車輛末趟完成後能否準時到達下一上車點（含 TDX 時段係數）。
  3. 篩距離：空車直線距離 ≤ max_detour_km（粗篩），OSRM 行程時間細算。
  4. 評分：OSRM 空車行程秒數最小者優先；同分則趟數少的車優先（均攤）。
  5. 指派後即時更新車輛狀態（末趟下車地點 → 新趟），供後續訂單使用。
"""
from __future__ import annotations

import math
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.route import RouteStop
from app.models.vehicle import Vehicle
from app.services import matrix as matrix_svc
from app.services import roster as roster_svc
from app.services import tdx_traffic

TW = timezone(timedelta(hours=8))
_SERVICE_BUFFER_SEC = 180   # 下車後作業緩衝（秒）
_DEFAULT_START_SEC  = 6 * 3600   # 無班表時預設 06:00 出發
_UNROUTABLE         = 9_999_999


# ── 工具 ─────────────────────────────────────────────────────────────────

def _to_sec(t) -> int | None:
    """datetime / time / str(HH:MM) → 一天中的秒數。"""
    if t is None:
        return None
    if isinstance(t, datetime):
        tw = t.astimezone(TW)
        return tw.hour * 3600 + tw.minute * 60 + tw.second
    if isinstance(t, dtime):
        return t.hour * 3600 + t.minute * 60 + t.second
    if isinstance(t, str):
        try:
            h, m = t.strip()[:5].split(":")
            return int(h) * 3600 + int(m) * 60
        except Exception:
            return None
    return None


def _haversine_m(lng1, lat1, lng2, lat2) -> float:
    if None in (lng1, lat1, lng2, lat2):
        return float("inf")
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _adjusted_sec(raw_sec: int, at_sec: int) -> int:
    """依 TDX 時段係數調整行程秒數（塞車時段自動拉長）。"""
    hour = max(0, at_sec) // 3600
    tf = tdx_traffic.get_time_factor(hour)
    return int(raw_sec / tf) if tf > 0.01 else raw_sec


# ── 主函式 ────────────────────────────────────────────────────────────────

def assign(
    db: Session,
    service_date: date,
    max_detour_km: float = 15.0,
    late_tolerance_min: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    回傳 {
      "assigned":          [ {order_id, passenger, pickup_time, vehicle, detour_km, reason} ],
      "still_unassigned":  [ {order_id, passenger, pickup_time, reason} ],
      "summary":           { total, assigned, unassigned, dry_run }
    }
    """
    # ── 1. 未排班訂單（有座標，依上車時間排序）──────────────────────────────
    unscheduled: list[Order] = list(db.scalars(
        select(Order).where(
            Order.service_date == service_date,
            Order.status == "imported",
            Order.pickup_lng.is_not(None),
            Order.dropoff_lng.is_not(None),
        ).order_by(Order.pickup_time)
    ).all())

    if not unscheduled:
        return {
            "assigned": [], "still_unassigned": [],
            "summary": {"total": 0, "assigned": 0, "unassigned": 0, "dry_run": dry_run},
        }

    # ── 2. 出勤車輛（roster 或 fallback 全 active） ──────────────────────────
    duty = roster_svc.available_vehicles(db, service_date)
    if not duty and not roster_svc.has_any_roster(db):
        # 無班表時 fallback：全 active 且未停派的車
        all_veh_ids = set(db.scalars(
            select(Vehicle.id).where(Vehicle.active.is_(True), Vehicle.suspended.is_(False))
        ).all())
        duty = {vid: (None, None) for vid in all_veh_ids}

    if not duty:
        return {
            "assigned": [],
            "still_unassigned": [_order_info(o, "無出勤車輛") for o in unscheduled],
            "summary": {"total": len(unscheduled), "assigned": 0,
                        "unassigned": len(unscheduled), "dry_run": dry_run},
        }

    vmap: dict[int, Vehicle] = {
        v.id: v for v in db.scalars(
            select(Vehicle).where(Vehicle.id.in_(duty.keys()))
        ).all()
    }

    # ── 3. 各車目前狀態（末趟下車座標＋預計完成秒數） ──────────────────────
    # 先取 delivery ETA
    delivery_eta: dict[int, int] = {}   # order_id -> 秒數
    for rs in db.scalars(
        select(RouteStop).where(
            RouteStop.service_date == service_date,
            RouteStop.kind == "delivery",
            RouteStop.order_id.is_not(None),
            RouteStop.eta.is_not(None),
        )
    ).all():
        s = _to_sec(rs.eta)
        if s is not None:
            delivery_eta[rs.order_id] = s

    # 既有排班，取各車末趟（最晚上車時間的那筆）
    scheduled: list[Order] = list(db.scalars(
        select(Order).where(
            Order.service_date == service_date,
            Order.status.in_(("scheduled", "ongoing", "done")),
            Order.assigned_vehicle_id.is_not(None),
        )
    ).all())

    # 建初始車輛狀態
    # {vid: {"lng","lat","free_sec","trip_count"}}
    veh_state: dict[int, dict] = {}
    for vid, (shift_start, _) in duty.items():
        v = vmap.get(vid)
        start_sec = shift_start or _DEFAULT_START_SEC
        veh_state[vid] = {
            "lng":        v.start_lng if v else None,
            "lat":        v.start_lat if v else None,
            "free_sec":   start_sec,
            "trip_count": 0,
        }

    # 用既有排班更新狀態（取末趟）
    by_veh: dict[int, list[Order]] = {}
    for o in scheduled:
        by_veh.setdefault(o.assigned_vehicle_id, []).append(o)

    for vid, orders in by_veh.items():
        if vid not in veh_state:
            continue
        # 取上車時間最晚的那筆
        last = max(orders, key=lambda o: _to_sec(o.pickup_time) or 0)
        # 估下車完成時間
        free_sec = (
            delivery_eta.get(last.id)
            or _to_sec(last.dropoff_time)
            or (_to_sec(last.pickup_time) or 0) + 3600  # fallback +1h
        ) + _SERVICE_BUFFER_SEC
        veh_state[vid] = {
            "lng":        last.dropoff_lng,
            "lat":        last.dropoff_lat,
            "free_sec":   free_sec,
            "trip_count": len(orders),
        }

    # ── 4. 建 OSRM 點集合（一次建矩陣） ──────────────────────────────────
    _pi: dict[tuple, int] = {}
    _pts: list[tuple[float, float]] = []

    def _pt(lng, lat) -> int | None:
        if lng is None or lat is None:
            return None
        k = (round(lng, 6), round(lat, 6))
        if k not in _pi:
            _pi[k] = len(_pts)
            _pts.append(k)
        return _pi[k]

    # 加入所有車輛目前位置 + 未排班訂單的上下車點
    for st in veh_state.values():
        _pt(st["lng"], st["lat"])
    for o in unscheduled:
        _pt(o.pickup_lng, o.pickup_lat)
        _pt(o.dropoff_lng, o.dropoff_lat)

    _mat = matrix_svc.build_matrix(_pts) if _pts else {"durations": []}
    _DUR = _mat.get("durations") or []

    def _travel(from_lng, from_lat, to_lng, to_lat, at_sec: int = 0) -> int:
        """OSRM 行程秒數（含 TDX 時段係數）；座標未知回傳 _UNROUTABLE。"""
        fi = _pt(from_lng, from_lat)
        ti = _pt(to_lng, to_lat)
        if fi is None or ti is None or not _DUR:
            return _UNROUTABLE
        try:
            raw = _DUR[fi][ti]
            if raw is None or raw >= _UNROUTABLE:
                return _UNROUTABLE
            return _adjusted_sec(int(raw), at_sec)
        except (IndexError, TypeError):
            return _UNROUTABLE

    # ── 5. Greedy 指派 ────────────────────────────────────────────────────
    assigned_results:   list[dict] = []
    still_unassigned:   list[dict] = []
    to_write:           list[tuple[int, int]] = []   # (order_id, vehicle_id)

    for o in unscheduled:
        pick_sec = _to_sec(o.pickup_time)
        if pick_sec is None:
            still_unassigned.append(_order_info(o, "無上車時間"))
            continue

        need_welfare = (o.vehicle_type == "welfare")

        best_vid:   int | None = None
        best_score: float = float("inf")

        for vid, st in veh_state.items():
            v = vmap.get(vid)
            if v is None:
                continue

            # 車種相容
            if need_welfare and v.type != "welfare":
                continue

            # 出勤時段：上車時間需在班表內
            _, shift_end = duty.get(vid, (None, None))
            if shift_end and pick_sec > shift_end:
                continue

            # 服務時段外：預設 06:00–18:00（若車輛自設則覆蓋）
            v_start = _to_sec(v.shift_start) or _DEFAULT_START_SEC
            v_end   = _to_sec(v.shift_end)   or (18 * 3600)
            if pick_sec < v_start or pick_sec > v_end:
                continue

            # 直線距離粗篩
            haversine_km = _haversine_m(st["lng"], st["lat"],
                                        o.pickup_lng, o.pickup_lat) / 1000
            if haversine_km > max_detour_km:
                continue

            # OSRM 空車行程（含 TDX 係數）
            detour_sec = _travel(
                st["lng"], st["lat"],
                o.pickup_lng, o.pickup_lat,
                at_sec=st["free_sec"],
            )
            if detour_sec >= _UNROUTABLE:
                continue

            # 時間可行性：車輛空閒後能否趕到（允許 late_tolerance_min 分鐘遲到）
            arrival_sec = st["free_sec"] + detour_sec
            if arrival_sec > pick_sec + late_tolerance_min * 60:
                continue

            # 評分：空車行程秒數（越小越好）；同分取趟數少的車
            score = (detour_sec, st["trip_count"])
            if score < (best_score, veh_state[best_vid]["trip_count"] if best_vid else 0):
                best_score = detour_sec
                best_vid   = vid

        if best_vid is None:
            # 找不到合適的車
            reason = _no_vehicle_reason(
                o, veh_state, vmap, duty, need_welfare, pick_sec, max_detour_km
            )
            still_unassigned.append(_order_info(o, reason))
            continue

        # ── 指派成功 ──
        v         = vmap[best_vid]
        st        = veh_state[best_vid]
        detour_km = round(_haversine_m(
            st["lng"], st["lat"], o.pickup_lng, o.pickup_lat) / 1000, 1)

        # 估此趟完成時間（供後續訂單用）
        trip_sec = _travel(
            o.pickup_lng, o.pickup_lat,
            o.dropoff_lng, o.dropoff_lat,
            at_sec=pick_sec,
        )
        est_done_sec = pick_sec + (trip_sec if trip_sec < _UNROUTABLE else 3600) + _SERVICE_BUFFER_SEC

        # 更新車輛狀態
        veh_state[best_vid] = {
            "lng":        o.dropoff_lng,
            "lat":        o.dropoff_lat,
            "free_sec":   est_done_sec,
            "trip_count": st["trip_count"] + 1,
        }
        to_write.append((o.id, best_vid))

        assigned_results.append({
            "order_id":    o.id,
            "passenger":   o.passenger_name,
            "pickup_time": o.pickup_time.astimezone(TW).strftime("%H:%M") if o.pickup_time else None,
            "vehicle":     v.plate,
            "vehicle_type": v.type,
            "detour_km":   detour_km,
            "reason":      f"空車 {detour_km} km，趟數 {st['trip_count']+1}",
        })

    # ── 6. 寫入 DB ────────────────────────────────────────────────────────
    if not dry_run and to_write:
        for oid, vid in to_write:
            o = db.get(Order, oid)
            if o:
                o.assigned_vehicle_id = vid
                o.status = "scheduled"
        db.commit()

    return {
        "assigned":         assigned_results,
        "still_unassigned": still_unassigned,
        "summary": {
            "total":       len(unscheduled),
            "assigned":    len(assigned_results),
            "unassigned":  len(still_unassigned),
            "dry_run":     dry_run,
        },
    }


# ── 輔助 ─────────────────────────────────────────────────────────────────

def _order_info(o: Order, reason: str) -> dict:
    return {
        "order_id":    o.id,
        "passenger":   o.passenger_name,
        "pickup_time": o.pickup_time.astimezone(TW).strftime("%H:%M") if o.pickup_time else None,
        "pickup":      o.pickup_address,
        "dropoff":     o.dropoff_address,
        "vehicle_type": o.vehicle_type,
        "reason":      reason,
    }


def _no_vehicle_reason(
    o: Order,
    veh_state: dict,
    vmap: dict,
    duty: dict,
    need_welfare: bool,
    pick_sec: int,
    max_detour_km: float,
) -> str:
    """產生詳細的無法指派原因。"""
    welfare_avail = any(
        v.type == "welfare" for vid, v in vmap.items() if vid in duty
    )
    if need_welfare and not welfare_avail:
        return "無可用福祉車"

    in_hours = [
        vid for vid, st in veh_state.items()
        if (not need_welfare or vmap.get(vid, Vehicle()).type == "welfare")
        and pick_sec >= (_to_sec(vmap[vid].shift_start) or 0 if vid in vmap else 0)
        and pick_sec <= (_to_sec(vmap[vid].shift_end) or 18*3600 if vid in vmap else 18*3600)
    ]
    if not in_hours:
        return "超出所有車輛服務時段"

    in_range = [
        vid for vid in in_hours
        if _haversine_m(
            veh_state[vid]["lng"], veh_state[vid]["lat"],
            o.pickup_lng, o.pickup_lat
        ) / 1000 <= max_detour_km
    ]
    if not in_range:
        return f"無車輛在 {max_detour_km} km 範圍內"

    return "時間衝突：所有鄰近車輛均無法準時抵達"
