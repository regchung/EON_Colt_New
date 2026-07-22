"""多智能體拍賣派遣系統。

每台車是獨立 VehicleAgent，同時對訂單池出價；
Coordinator 裁決最低價得標，逐輪迭代直到無人出價。

規則：
  - welfare 車可接 welfare + normal 訂單
  - normal  車只能接 normal 訂單
  - 遲到上限 10 分鐘（可調）
  - 行程時間 = OSRM ÷ TDX 時段係數（依出發時刻）
              ÷ TDX 即時區域係數（當下快取，可選）
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.route import RouteStop
from app.models.vehicle import Vehicle
from app.services import matrix as matrix_svc
from app.services import roster as roster_svc
from app.services import tdx_traffic

TW = timezone(timedelta(hours=8))
_UNROUTABLE      = 9_999_999
_SERVICE_BUF_SEC = 180   # 下車後緩衝 3 分鐘
_DEFAULT_START   = 6 * 3600   # 無班表預設 06:00
_LATE_TOL_SEC    = 10 * 60    # 允許遲到上限


# ── 工具函式 ──────────────────────────────────────────────────────────────

def _to_sec(t) -> int | None:
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


def _tdx_adjusted(raw_sec: int, departure_sec: int,
                  from_lng, from_lat, to_lng, to_lat) -> int:
    """OSRM 行程秒數加 TDX 雙層調整。

    Layer-1 靜態時段係數（依預計出發時刻，預測未來路況）。
    Layer-2 即時區域係數（TDX VD 快取，若有資料且出發在 30 分鐘內）。
    兩層取較嚴（係數較小）的那個。
    """
    hour = max(0, departure_sec) // 3600
    tf_time = tdx_traffic.get_time_factor(hour)

    # 即時路況：只有出發時刻在近 30 分鐘內才採用
    # （遠期班次用即時快照會失真）
    current_sec = (
        datetime.now(TW).hour * 3600
        + datetime.now(TW).minute * 60
        + datetime.now(TW).second
    )
    if abs(departure_sec - current_sec) < 1800 and from_lng is not None:
        from_dist = tdx_traffic._nearest_district(from_lng, from_lat)
        to_dist   = tdx_traffic._nearest_district(to_lng, to_lat)
        tf_live   = tdx_traffic.get_pair_factor(from_dist or "", to_dist or "")
        tf = min(tf_time, tf_live) if tf_live < 0.99 else tf_time
    else:
        tf = tf_time

    return int(raw_sec / tf) if tf > 0.01 else raw_sec


# ── 最佳化旗標 ───────────────────────────────────────────────────────────

@dataclass
class OptFlags:
    """派遣最佳化選項（可逐一啟用）。"""
    # ① 福祉車護欄：welfare 車對 normal 訂單出價 × 倍率，讓 normal 車優先接 normal
    welfare_guard:      bool  = True
    welfare_guard_mul:  float = 1.1

    # ② 對數負載均衡：出價 × (1 + ln(趟次+1) × 係數)，防單車包攬
    log_load_balance:   bool  = True
    log_lb_coeff:       float = 0.05

    # ③ 第二輪補救：首輪失敗的訂單用放寬遲到容忍度再跑一次（0 = 不啟用）
    second_pass_min:    int   = 15

    # 每車每日趟次上限（0 = 不限）
    max_trips_welfare:  int   = 16   # 福祉車一班上限
    max_trips_normal:   int   = 14   # 一般車一班上限

    # ④ 前瞻保護（預留）：得標前先確認不會封死孤兒訂單的唯一服務車
    lookahead:          bool  = False

    # ⑤ 共乘聚合（預留）：pickup 時間差 ≤ N 分鐘且地點 ≤ M km 視為同趟
    shared_ride_min:    int   = 0    # 0 = 不啟用
    shared_ride_km:     float = 1.0


# ── Agent 狀態 ────────────────────────────────────────────────────────────

@dataclass
class AgentState:
    vehicle_id:  int
    plate:       str
    v_type:      str          # "welfare" | "normal"
    cur_lng:     float | None
    cur_lat:     float | None
    free_sec:    int          # 何時空閒（一天中的秒數）
    shift_end:   int | None   # 班表結束時間（秒）
    trip_count:  int = 0
    schedule:    list[int] = field(default_factory=list)


# ── Vehicle Agent ─────────────────────────────────────────────────────────

class VehicleAgent:
    def __init__(self, state: AgentState,
                 pt_index: dict[tuple, int],
                 dur_mat:  list[list[float]],
                 opts:     OptFlags | None = None,
                 late_tol_sec: int = _LATE_TOL_SEC):
        self.s         = state
        self._pi       = pt_index
        self._dur      = dur_mat
        self._opts     = opts or OptFlags()
        self._late_tol = late_tol_sec

    # ── 規則：車種相容性 ──────────────────────────────────────────────────
    def can_serve(self, order: Order) -> bool:
        if order.vehicle_type == "welfare" and self.s.v_type == "normal":
            return False
        return True

    # ── 出價 ──────────────────────────────────────────────────────────────
    def bid(self, order: Order) -> float | None:
        """
        基礎出價 = 當下位置 → 訂單起點的 TDX 行程秒數。
        硬性條件：不得遲到超過 late_tol_sec。
        最佳化項目（依 OptFlags）：
          ① welfare 車對 normal 訂單出價乘以護欄倍率
          ② 對數負載均衡，防單車包攬所有訂單
        """
        if not self.can_serve(order):
            return None

        # 每日趟次上限
        opts = self._opts
        max_trips = (opts.max_trips_welfare if self.s.v_type == "welfare"
                     else opts.max_trips_normal)
        if max_trips > 0 and self.s.trip_count >= max_trips:
            return None

        pick_sec = _to_sec(order.pickup_time)
        if pick_sec is None:
            return None

        if self.s.shift_end and pick_sec > self.s.shift_end:
            return None

        travel = self._osrm_travel(
            self.s.cur_lng, self.s.cur_lat,
            order.pickup_lng, order.pickup_lat,
            departure_sec=self.s.free_sec,
        )
        if travel >= _UNROUTABLE:
            return None

        if self.s.free_sec + travel - pick_sec > self._late_tol:
            return None

        price = float(travel)

        # ① 福祉車護欄
        if (opts.welfare_guard
                and self.s.v_type == "welfare"
                and order.vehicle_type == "normal"):
            price *= opts.welfare_guard_mul

        # ② 對數負載均衡
        if opts.log_load_balance and self.s.trip_count > 0:
            price *= (1 + math.log(self.s.trip_count + 1) * opts.log_lb_coeff)

        return price

    # ── 得標後更新狀態 ────────────────────────────────────────────────────
    def accept(self, order: Order) -> int:
        """更新車輛狀態，回傳 dropoff_sec（送達時刻，秒）。"""
        pick_sec = _to_sec(order.pickup_time) or self.s.free_sec
        trip_sec = self._osrm_travel(
            order.pickup_lng, order.pickup_lat,
            order.dropoff_lng, order.dropoff_lat,
            departure_sec=pick_sec,
        )
        raw_trip  = trip_sec if trip_sec < _UNROUTABLE else 3600
        dropoff_sec = pick_sec + raw_trip
        done_sec    = dropoff_sec + _SERVICE_BUF_SEC
        self.s.cur_lng    = order.dropoff_lng
        self.s.cur_lat    = order.dropoff_lat
        self.s.free_sec   = done_sec
        self.s.trip_count += 1
        self.s.schedule.append(order.id)
        return dropoff_sec

    # ── OSRM + TDX 行程 ──────────────────────────────────────────────────
    def _pt(self, lng, lat) -> int | None:
        if lng is None or lat is None:
            return None
        return self._pi.get((round(lng, 6), round(lat, 6)))

    def _osrm_travel(self, from_lng, from_lat, to_lng, to_lat,
                     departure_sec: int = 0) -> int:
        fi = self._pt(from_lng, from_lat)
        ti = self._pt(to_lng, to_lat)
        if fi is None or ti is None or not self._dur:
            return _UNROUTABLE
        try:
            raw = self._dur[fi][ti]
            if raw is None or raw >= _UNROUTABLE:
                return _UNROUTABLE
            return _tdx_adjusted(int(raw), departure_sec,
                                 from_lng, from_lat, to_lng, to_lat)
        except (IndexError, TypeError):
            return _UNROUTABLE


# ── Sequential Time-Ordered Coordinator ──────────────────────────────────

class AuctionCoordinator:
    """按照訂單接送時間由早到晚逐筆競標。"""
    def __init__(self, agents: list[VehicleAgent], orders: list[Order]):
        self.agents = agents
        self.pool   = sorted(orders, key=lambda o: _to_sec(o.pickup_time) or 0)

    def run(self) -> tuple[list[dict], list[Order]]:
        """
        回傳 (assigned_list, unscheduled_list)。
        """
        assigned:     list[dict]  = []
        unscheduled:  list[Order] = []

        for order in self.pool:
            pick_sec = _to_sec(order.pickup_time)

            # 各車出價（在任務中的車 bid() 會因 free_sec 過晚而返回 None）
            offers: list[tuple[float, VehicleAgent]] = []
            for agent in self.agents:
                price = agent.bid(order)
                if price is not None:
                    offers.append((price, agent))

            if not offers:
                unscheduled.append(order)
                continue

            # 最低出價得標
            best_price, winner = min(offers, key=lambda x: x[0])
            detour_km = round(
                _haversine_m(winner.s.cur_lng, winner.s.cur_lat,
                             order.pickup_lng, order.pickup_lat) / 1000, 1
            )
            trip_no     = winner.s.trip_count + 1
            dropoff_sec = winner.accept(order)   # 取得送達時刻（秒）

            # 轉成帶時區 datetime（以 TW 零點為基準）
            _midnight_tw = datetime.combine(
                order.pickup_time.astimezone(TW).date() if order.pickup_time else datetime.now(TW).date(),
                dtime(0), tzinfo=TW,
            ) if True else None
            dropoff_dt = (_midnight_tw + timedelta(seconds=dropoff_sec)) if _midnight_tw else None

            assigned.append({
                "order_id":     order.id,
                "passenger":    order.passenger_name,
                "pickup_time":  (order.pickup_time.astimezone(TW).strftime("%H:%M")
                                 if order.pickup_time else None),
                "dropoff_sec":  dropoff_sec,
                "dropoff_eta":  dropoff_dt.isoformat() if dropoff_dt else None,
                "vehicle":      winner.s.plate,
                "vehicle_plate": winner.s.plate,
                "vehicle_type": winner.s.v_type,
                "bid_score":    round(best_price, 1),
                "trip_no":      trip_no,
                "detour_km":    detour_km,
            })

        return assigned, unscheduled


# ── 主函式 ────────────────────────────────────────────────────────────────

def run(
    db: Session,
    service_date: date,
    late_tolerance_min: int = 10,
    dry_run: bool = True,
    reset_scheduled: bool = False,
    # 最佳化選項（對應 OptFlags 欄位，None = 使用預設值）
    welfare_guard:     bool | None  = None,
    welfare_guard_mul: float | None = None,
    log_load_balance:  bool | None  = None,
    log_lb_coeff:      float | None = None,
    second_pass_min:   int | None   = None,
    max_trips_welfare: int | None   = None,   # 福祉車每日趟次上限
    max_trips_normal:  int | None   = None,   # 一般車每日趟次上限
    lookahead:         bool | None  = None,   # 預留
    shared_ride_min:   int | None   = None,   # 預留
    shared_ride_km:    float | None = None,   # 預留
) -> dict[str, Any]:
    """
    對 service_date 執行多智能體拍賣派遣。

    reset_scheduled=False（預設）→ 只處理 imported 訂單，車輛從末趟位置繼續
    reset_scheduled=True        → 清除所有 scheduled 指派，從頭完整重排全日班表

    最佳化選項（不傳則使用 OptFlags 預設值）：
      welfare_guard      ① 福祉車護欄（預設 True，倍率 1.1）
      log_load_balance   ② 對數負載均衡（預設 True，係數 0.05）
      second_pass_min    ③ 第二輪補救寬限分鐘（預設 15；0 = 不啟用）
      lookahead          ④ 前瞻保護（預留，尚未實作）
      shared_ride_min/km ⑤ 共乘聚合（預留，尚未實作）
    """
    late_tol_sec = late_tolerance_min * 60

    # 組裝 OptFlags（只覆寫有傳入的參數）
    opts = OptFlags()
    if welfare_guard     is not None: opts.welfare_guard     = welfare_guard
    if welfare_guard_mul is not None: opts.welfare_guard_mul = welfare_guard_mul
    if log_load_balance  is not None: opts.log_load_balance  = log_load_balance
    if log_lb_coeff      is not None: opts.log_lb_coeff      = log_lb_coeff
    if second_pass_min   is not None: opts.second_pass_min   = second_pass_min
    if max_trips_welfare is not None: opts.max_trips_welfare = max_trips_welfare
    if max_trips_normal  is not None: opts.max_trips_normal  = max_trips_normal
    if lookahead         is not None: opts.lookahead         = lookahead
    if shared_ride_min   is not None: opts.shared_ride_min   = shared_ride_min
    if shared_ride_km    is not None: opts.shared_ride_km    = shared_ride_km

    # ── 1. 訂單池 ─────────────────────────────────────────────────────────
    if reset_scheduled:
        status_filter = Order.status.in_(("imported", "scheduled"))
    else:
        status_filter = (Order.status == "imported")

    orders: list[Order] = list(db.scalars(
        select(Order).where(
            Order.service_date == service_date,
            status_filter,
            Order.pickup_lng.is_not(None),
            Order.dropoff_lng.is_not(None),
        ).order_by(Order.pickup_time)
    ).all())

    if not orders:
        return _empty_result(dry_run)

    # ── 2. 出勤車輛 ───────────────────────────────────────────────────────
    duty = roster_svc.available_vehicles(db, service_date)
    if not duty and not roster_svc.has_any_roster(db):
        all_ids = list(db.scalars(
            select(Vehicle.id).where(
                Vehicle.active.is_(True), Vehicle.suspended.is_(False)
            )
        ).all())
        duty = {vid: (None, None) for vid in all_ids}

    if not duty:
        return {
            "assigned": [],
            "unscheduled": [_order_summary(o, "無出勤車輛") for o in orders],
            "summary": {"total": len(orders), "assigned": 0,
                        "unscheduled": len(orders), "rounds": 0, "dry_run": dry_run},
        }

    vmap: dict[int, Vehicle] = {
        v.id: v for v in db.scalars(
            select(Vehicle).where(Vehicle.id.in_(duty.keys()))
        ).all()
    }

    # ── 3. 既有排班（reset_scheduled 時跳過，全部重排）──────────────────
    by_veh: dict[int, list[Order]] = {}
    delivery_eta: dict[int, int] = {}

    if not reset_scheduled:
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

        scheduled: list[Order] = list(db.scalars(
            select(Order).where(
                Order.service_date == service_date,
                Order.status.in_(("scheduled", "ongoing", "done")),
                Order.assigned_vehicle_id.is_not(None),
            )
        ).all())
        for o in scheduled:
            by_veh.setdefault(o.assigned_vehicle_id, []).append(o)

    # ── 4. 初始化 Agent 狀態 ─────────────────────────────────────────────
    agent_states: list[AgentState] = []
    for vid, (shift_start, shift_end) in duty.items():
        v = vmap.get(vid)
        if v is None:
            continue
        start_sec = shift_start or _DEFAULT_START
        shift_end_sec = shift_end

        vorders = by_veh.get(vid, [])
        if vorders:
            # 增量模式：從末趟結束位置繼續
            last = max(vorders, key=lambda o: _to_sec(o.pickup_time) or 0)
            free_sec = (
                delivery_eta.get(last.id)
                or _to_sec(last.dropoff_time)
                or (_to_sec(last.pickup_time) or 0) + 3600
            ) + _SERVICE_BUF_SEC
            cur_lng = last.dropoff_lng
            cur_lat = last.dropoff_lat
            trip_count = len(vorders)
        else:
            # 全重排 or 無既有行程：從出發點、班表起始時刻出發
            free_sec   = start_sec
            cur_lng    = v.start_lng
            cur_lat    = v.start_lat
            trip_count = 0

        agent_states.append(AgentState(
            vehicle_id = vid,
            plate      = v.plate,
            v_type     = v.type or "normal",
            cur_lng    = cur_lng,
            cur_lat    = cur_lat,
            free_sec   = free_sec,
            shift_end  = shift_end_sec,
            trip_count = trip_count,
        ))

    # ── 5. 建 OSRM 矩陣（一次建好，所有 Agent 共用）─────────────────────
    pt_index: dict[tuple, int] = {}
    pts: list[tuple[float, float]] = []

    def _add_pt(lng, lat):
        if lng is None or lat is None:
            return
        k = (round(lng, 6), round(lat, 6))
        if k not in pt_index:
            pt_index[k] = len(pts)
            pts.append(k)

    for st in agent_states:
        _add_pt(st.cur_lng, st.cur_lat)
    for o in orders:
        _add_pt(o.pickup_lng, o.pickup_lat)
        _add_pt(o.dropoff_lng, o.dropoff_lat)

    mat_result = matrix_svc.build_matrix(pts) if pts else {"durations": []}
    dur_mat = mat_result.get("durations") or []

    # ── 6. 建 Agent 清單 ─────────────────────────────────────────────────
    agents = [
        VehicleAgent(st, pt_index, dur_mat, opts=opts, late_tol_sec=late_tol_sec)
        for st in agent_states
    ]

    # ── 7. 第一輪拍賣（正常容忍度）────────────────────────────────────────
    coordinator = AuctionCoordinator(agents, orders)
    assigned_list, remaining = coordinator.run()

    # ── 7b. 第二輪補救（放寬遲到容忍度）─────────────────────────────────
    if opts.second_pass_min > 0 and remaining:
        second_tol = opts.second_pass_min * 60
        for ag in agents:
            ag._late_tol = second_tol
        coord2 = AuctionCoordinator(agents, remaining)
        assigned2, remaining = coord2.run()
        for item in assigned2:
            item["pass"] = 2   # 標記為第二輪補救
        assigned_list.extend(assigned2)
        # 還原 late_tol（dry_run 結束後不影響，non-dry_run 需一致）
        for ag in agents:
            ag._late_tol = late_tol_sec

    unscheduled_list = [
        _order_summary(o, _reason(o, agent_states, vmap))
        for o in remaining
    ]

    # ── 8. 寫入 DB ────────────────────────────────────────────────────────
    if not dry_run:
        plate_to_vid = {v.plate: v.id for v in vmap.values()}

        if reset_scheduled:
            # 先清除當天所有 scheduled 指派
            for o in db.scalars(
                select(Order).where(
                    Order.service_date == service_date,
                    Order.status == "scheduled",
                )
            ).all():
                o.assigned_vehicle_id = None
                o.status = "imported"
            db.flush()

        for item in assigned_list:
            vid = plate_to_vid.get(item["vehicle"])
            if vid is None:
                continue
            o = db.get(Order, item["order_id"])
            if o:
                o.assigned_vehicle_id = vid
                o.status = "scheduled"
        db.commit()

    # ── 9. 各車得標彙整 ──────────────────────────────────────────────────
    vehicle_summary: dict[str, dict] = {}
    for item in assigned_list:
        vp = item["vehicle"]
        if vp not in vehicle_summary:
            vehicle_summary[vp] = {
                "vehicle":     vp,
                "vehicle_type": item["vehicle_type"],
                "trips":       [],
            }
        vehicle_summary[vp]["trips"].append({
            "order_id":    item["order_id"],
            "passenger":   item["passenger"],
            "pickup_time": item["pickup_time"],
            "trip_no":     item["trip_no"],
            "detour_km":   item["detour_km"],
            "bid_score":   item["bid_score"],
        })

    return {
        "assigned":         assigned_list,
        "unscheduled":      unscheduled_list,
        "vehicle_summary":  list(vehicle_summary.values()),
        "summary": {
            "total":          len(orders),
            "assigned":       len(assigned_list),
            "unscheduled":    len(remaining),
            "vehicles_used":  len(vehicle_summary),
            "dry_run":        dry_run,
        },
    }


# ── 輔助 ──────────────────────────────────────────────────────────────────

def _empty_result(dry_run: bool) -> dict:
    return {
        "assigned": [], "unscheduled": [], "vehicle_summary": [],
        "summary": {"total": 0, "assigned": 0, "unscheduled": 0,
                    "vehicles_used": 0, "dry_run": dry_run},
    }


def _order_summary(o: Order, reason: str = "") -> dict:
    return {
        "order_id":    o.id,
        "passenger":   o.passenger_name,
        "pickup_time": (o.pickup_time.astimezone(TW).strftime("%H:%M")
                        if o.pickup_time else None),
        "vehicle_type": o.vehicle_type,
        "pickup":      o.pickup_address,
        "dropoff":     o.dropoff_address,
        "reason":      reason,
    }


def _reason(o: Order, states: list[AgentState], vmap: dict) -> str:
    """推斷無法指派原因。"""
    pick_sec = _to_sec(o.pickup_time)
    need_welfare = (o.vehicle_type == "welfare")

    welfare_avail = any(st.v_type == "welfare" for st in states)
    if need_welfare and not welfare_avail:
        return "無可用福祉車"

    in_time = [
        st for st in states
        if (not need_welfare or st.v_type == "welfare")
        and (st.shift_end is None or (pick_sec or 0) <= st.shift_end)
    ]
    if not in_time:
        return "超出所有車輛服務時段"

    in_range = [
        st for st in in_time
        if _haversine_m(st.cur_lng, st.cur_lat,
                        o.pickup_lng, o.pickup_lat) / 1000 <= 20
    ]
    if not in_range:
        return "無車輛在 20 km 範圍內"

    return "時間衝突：所有鄰近車輛均無法準時抵達"
