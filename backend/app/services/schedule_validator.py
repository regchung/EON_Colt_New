"""排班合理性檢查。

檢查兩類衝突：
1. overlap   — 上一趟預計下車時間 > 下一趟上車時間（時間重疊）
2. roundtrip — 同一乘客去程尚未到達目的地，回程已排入（往返緊接）

預計下車時間來源（優先序）：
  a. route_stop 裡的 delivery ETA（VROOM 計算結果）
  b. orders.dropoff_time（人工班表帶入）
  c. OSRM 估算 × TDX 即時路況係數（塞車時間自動拉長）

附加功能：
  - 每趟標注鄰近 TDX 道路事件（施工/事故）告警
"""
from __future__ import annotations

import math
from datetime import date, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.route import RouteStop
from app.models.vehicle import Vehicle
from app.services import matrix as matrix_svc
from app.services import tdx_traffic
from app.services import tdx_road_alert

TW = timezone(timedelta(hours=8))
_SERVICE_BUFFER_SEC = 3 * 60   # 下車後固定作業緩衝（3 分鐘）
_ROUNDTRIP_DIST_M   = 800      # 判定「同一地點」的直線距離上限（公尺）


# ── 工具函式 ───────────────────────────────────────────────────────────────

def _mins(dt) -> int | None:
    if dt is None:
        return None
    t = dt.astimezone(TW)
    return t.hour * 60 + t.minute


def _hhmm(dt) -> str | None:
    if dt is None:
        return None
    t = dt.astimezone(TW)
    return f"{t.hour:02d}:{t.minute:02d}"


def _haversine_m(lng1, lat1, lng2, lat2) -> float:
    """兩點直線距離（公尺）。"""
    if None in (lng1, lat1, lng2, lat2):
        return float("inf")
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _is_same_place(lng1, lat1, lng2, lat2) -> bool:
    return _haversine_m(lng1, lat1, lng2, lat2) <= _ROUNDTRIP_DIST_M


# ── 主函式 ────────────────────────────────────────────────────────────────

def validate(db: Session, service_date: date) -> dict[str, Any]:
    """
    回傳 {
      "service_date": "YYYY-MM-DD",
      "violations": [ { vehicle, driver, type, orders, detail } ],
      "summary": { total, by_type }
    }
    """
    # 1. 取當日已指派訂單
    orders = list(db.scalars(
        select(Order).where(
            Order.service_date == service_date,
            Order.status.in_(("scheduled", "ongoing", "done")),
            Order.assigned_vehicle_id.is_not(None),
        )
    ).all())

    if not orders:
        return {"service_date": str(service_date), "violations": [], "summary": {"total": 0, "by_type": {}}}

    # 2. 取 route_stop delivery ETA（最精確的下車時間）
    delivery_eta: dict[int, int | None] = {}   # order_id -> 分鐘數
    delivery_eta_hhmm: dict[int, str] = {}
    for rs in db.scalars(
        select(RouteStop).where(
            RouteStop.service_date == service_date,
            RouteStop.kind == "delivery",
            RouteStop.order_id.is_not(None),
            RouteStop.eta.is_not(None),
        )
    ).all():
        m = _mins(rs.eta)
        if m is not None:
            delivery_eta[rs.order_id] = m
            delivery_eta_hhmm[rs.order_id] = _hhmm(rs.eta)

    # 3. 預先拉取 TDX 道路事件（C）——一次呼叫、全趟共用快取
    road_alerts = tdx_road_alert.get_alerts()

    # 4. 建 OSRM 距離矩陣（用於估算無 ETA 趟次的下車時間）
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

    ord_idx: dict[int, tuple[int, int]] = {}
    for o in orders:
        pi = _pt(o.pickup_lng, o.pickup_lat)
        di = _pt(o.dropoff_lng, o.dropoff_lat)
        if pi is not None and di is not None:
            ord_idx[o.id] = (pi, di)

    _mat = matrix_svc.build_matrix(_pts) if _pts else {"durations": []}
    _DUR = _mat.get("durations") or []

    def _travel_sec(a, b) -> int:
        if a is None or b is None or not _DUR:
            return 0
        try:
            v = _DUR[a][b]
            return int(v) if v is not None else 0
        except IndexError:
            return 0

    def _est_dropoff_min(o: Order) -> int | None:
        """估算下車時間（分鐘數）。
        OSRM 裸行程 × TDX 時段塞車係數（factor<1 → 除之 → 時間變長）。
        """
        # a. route_stop delivery ETA（VROOM 結果最準，直接用）
        if o.id in delivery_eta:
            return delivery_eta[o.id]
        # b. orders.dropoff_time（人工班表帶入）
        m = _mins(o.dropoff_time)
        if m is not None:
            return m
        # c. OSRM 估算 + TDX 時段係數
        pick_m = _mins(o.pickup_time)
        if pick_m is None:
            return None
        if o.id in ord_idx:
            pu_i, do_i = ord_idx[o.id]
            raw_secs = _travel_sec(pu_i, do_i)
            # TDX 時段係數：上車時刻的時段
            hour = pick_m // 60
            tf = tdx_traffic.get_time_factor(hour)   # e.g. 0.48 表示早峰嚴重塞車
            adjusted_secs = int(raw_secs / tf) if tf > 0 else raw_secs
            return pick_m + (adjusted_secs + _SERVICE_BUFFER_SEC) // 60
        return None

    def _est_dropoff_label(o: Order) -> str:
        """下車時間的顯示字串與來源。"""
        if o.id in delivery_eta_hhmm:
            return delivery_eta_hhmm[o.id] + "（VROOM）"
        if _mins(o.dropoff_time) is not None:
            return _hhmm(o.dropoff_time) + "（人工）"
        m = _est_dropoff_min(o)
        if m is not None:
            hour = (_mins(o.pickup_time) or 0) // 60
            tf = tdx_traffic.get_time_factor(hour)
            suffix = f"OSRM+TDX係數{tf:.2f}" if tf < 0.99 else "OSRM估"
            return f"{m//60:02d}:{m%60:02d}（{suffix}）"
        return "?"

    def _trip_alerts(o: Order) -> list[dict]:
        """回傳影響此趟的 TDX 道路事件摘要（C 功能）。"""
        matched = tdx_road_alert.near_route(
            o.pickup_lng, o.pickup_lat,
            o.dropoff_lng, o.dropoff_lat,
            alerts=road_alerts,
        )
        return [
            {
                "type":        a["type"],
                "description": a["description"],
                "road":        a["road"],
                "start_time":  a["start_time"],
                "end_time":    a["end_time"],
            }
            for a in matched
        ]

    # 5. 取車輛名稱
    vids = {o.assigned_vehicle_id for o in orders}
    vmap = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(vids))).all()}

    # 5. 分組並排序
    by_veh: dict[int, list[Order]] = {}
    for o in orders:
        by_veh.setdefault(o.assigned_vehicle_id, []).append(o)

    violations: list[dict] = []

    for vid, vorders in by_veh.items():
        v = vmap.get(vid)
        plate = v.plate if v else f"#{vid}"
        driver = None  # 可從 drv_by_veh 擴充，此處略

        # 依上車時間排序
        vorders.sort(key=lambda o: o.pickup_time or date.today())

        for i in range(len(vorders) - 1):
            cur  = vorders[i]
            nxt  = vorders[i + 1]

            cur_drop  = _est_dropoff_min(cur)
            nxt_pick  = _mins(nxt.pickup_time)

            if cur_drop is None or nxt_pick is None:
                continue

            overlap_min = cur_drop - nxt_pick

            # ── 判斷是否同起同終（共乘）→ 跳過 ──────────────────────────
            same_route = (
                _is_same_place(cur.pickup_lng, cur.pickup_lat,
                               nxt.pickup_lng, nxt.pickup_lat)
                and _is_same_place(cur.dropoff_lng, cur.dropoff_lat,
                                   nxt.dropoff_lng, nxt.dropoff_lat)
            )
            if same_route:
                continue

            if overlap_min <= 0:
                continue   # 無衝突

            # ── 判斷是否往返趟 ────────────────────────────────────────────
            same_passenger = (
                (cur.passenger_name or "").strip()
                == (nxt.passenger_name or "").strip()
                and (cur.passenger_name or "").strip() != ""
            )
            # 去程下車地點 ≈ 回程上車地點
            dropoff_eq_pickup = _is_same_place(
                cur.dropoff_lng, cur.dropoff_lat,
                nxt.pickup_lng,  nxt.pickup_lat,
            )
            is_roundtrip = same_passenger and dropoff_eq_pickup

            vtype = "roundtrip" if is_roundtrip else "overlap"

            violations.append({
                "vehicle":      plate,
                "vehicle_id":   vid,
                "driver":       driver,
                "type":         vtype,
                "overlap_min":  overlap_min,
                "cur": {
                    "order_id":    cur.id,
                    "passenger":   cur.passenger_name,
                    "pickup_time": _hhmm(cur.pickup_time),
                    "est_dropoff": _est_dropoff_label(cur),
                    "pickup":      cur.pickup_address,
                    "dropoff":     cur.dropoff_address,
                    "road_alerts": _trip_alerts(cur),
                },
                "nxt": {
                    "order_id":    nxt.id,
                    "passenger":   nxt.passenger_name,
                    "pickup_time": _hhmm(nxt.pickup_time),
                    "pickup":      nxt.pickup_address,
                    "dropoff":     nxt.dropoff_address,
                    "road_alerts": _trip_alerts(nxt),
                },
                "detail": (
                    f"{'往返衝突' if is_roundtrip else '時間重疊'}："
                    f"訂單{cur.id}({cur.passenger_name}) "
                    f"預計{_est_dropoff_label(cur)}才下車，"
                    f"但訂單{nxt.id}({nxt.passenger_name}) "
                    f"{_hhmm(nxt.pickup_time)}就要上車，"
                    f"重疊{overlap_min}分鐘"
                ),
            })

    # 6. 跨趟往返掃描：同一乘客、去程下車地點 ≈ 回程上車地點，且存在時間重疊
    #    補捉中間夾其他乘客趟次的情況（如葉俊逸）
    already_rt: set[tuple[int, int]] = {
        (v["cur"]["order_id"], v["nxt"]["order_id"])
        for v in violations if v["type"] == "roundtrip"
    }
    for vid, vorders in by_veh.items():
        v = vmap.get(vid)
        plate = v.plate if v else f"#{vid}"
        vorders.sort(key=lambda o: o.pickup_time or date.today())
        # 按乘客分組，找同一乘客的所有趟次配對
        by_pax: dict[str, list[Order]] = {}
        for o in vorders:
            name = (o.passenger_name or "").strip()
            if name:
                by_pax.setdefault(name, []).append(o)
        for name, porders in by_pax.items():
            if len(porders) < 2:
                continue
            for i in range(len(porders)):
                for j in range(i + 1, len(porders)):
                    out = porders[i]
                    ret = porders[j]
                    # 跳過已收錄的連續往返
                    if (out.id, ret.id) in already_rt:
                        continue
                    # 去程下車地點 ≈ 回程上車地點
                    if not _is_same_place(
                        out.dropoff_lng, out.dropoff_lat,
                        ret.pickup_lng,  ret.pickup_lat,
                    ):
                        continue
                    out_drop = _est_dropoff_min(out)
                    ret_pick = _mins(ret.pickup_time)
                    if out_drop is None or ret_pick is None:
                        continue
                    overlap_min = out_drop - ret_pick
                    if overlap_min <= 0:
                        continue
                    violations.append({
                        "vehicle":     plate,
                        "vehicle_id":  vid,
                        "driver":      None,
                        "type":        "roundtrip",
                        "overlap_min": overlap_min,
                        "cur": {
                            "order_id":    out.id,
                            "passenger":   out.passenger_name,
                            "pickup_time": _hhmm(out.pickup_time),
                            "est_dropoff": _est_dropoff_label(out),
                            "pickup":      out.pickup_address,
                            "dropoff":     out.dropoff_address,
                            "road_alerts": _trip_alerts(out),
                        },
                        "nxt": {
                            "order_id":    ret.id,
                            "passenger":   ret.passenger_name,
                            "pickup_time": _hhmm(ret.pickup_time),
                            "pickup":      ret.pickup_address,
                            "dropoff":     ret.dropoff_address,
                            "road_alerts": _trip_alerts(ret),
                        },
                        "detail": (
                            f"往返衝突（跨趟）：訂單{out.id}({name}) "
                            f"去程預計{_est_dropoff_label(out)}才抵達，"
                            f"但回程訂單{ret.id} {_hhmm(ret.pickup_time)}就要接，"
                            f"重疊{overlap_min}分鐘"
                        ),
                    })
                    already_rt.add((out.id, ret.id))

    # 依車號 + 去程上車時間排序輸出
    violations.sort(key=lambda x: (x["vehicle"], x["cur"]["pickup_time"] or ""))

    by_type: dict[str, int] = {}
    for v in violations:
        by_type[v["type"]] = by_type.get(v["type"], 0) + 1

    # 全域道路事件彙整（有座標的事件）
    road_alert_summary = [
        {
            "type":        a["type"],
            "description": a["description"],
            "road":        a["road"],
            "start_time":  a["start_time"],
            "end_time":    a["end_time"],
            "severity":    a.get("severity", ""),
        }
        for a in road_alerts
        if a.get("lng") is not None
    ]

    return {
        "service_date": str(service_date),
        "violations":   violations,
        "road_alerts":  road_alert_summary,
        "summary": {
            "total":        len(violations),
            "by_type":      by_type,
            "road_alerts":  len(road_alert_summary),
        },
    }
