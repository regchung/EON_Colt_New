"""派遣相關端點(本階段:距離矩陣引擎驗證;下一步:VROOM 排班)。"""
from datetime import date, datetime, timedelta, timezone

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.dispatch_comparison import DispatchComparison
from app.models.dispatch_history import DispatchHistory
from app.models.fleet_calibration import FleetCalibration
from app.models.driver import Driver
from app.models.driver_vehicle_assignment import DriverVehicleAssignment
from app.models.order import Order
from app.models.pool_projection import PoolProjection
from app.models.route import RouteStop
from app.models.unassigned_record import UnassignedRecord
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import (
    ai_dispatch, assistant, calibration, comparison, comparison_export, dispatch_export,
    dispatcher, driver_affinity, forecast, matrix, osrm, pool_suggest, recurring_pairs,
    zone_affinity,
)
from app.services import vehicle_suggest as vehicle_suggest_svc
from app.services import settings as app_settings
from app.services import schedule_validator
from app.services import unscheduled_assigner
from app.services import conflict_resolver
from app.services import agent_dispatcher

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

# 每車一個顏色(地圖用)
_COLORS = ["#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#bfef45"]


@router.post("/run")
def run(
    service_date: date,
    ai: bool = False,
    reset_scheduled: bool = True,
    late_tolerance_min: int = 10,
    max_trips_welfare: int = 16,
    max_trips_normal: int = 14,
    db: Session = Depends(get_db),
):
    """多智能體拍賣派遣（主要派遣入口）。

    預設行為：清除當日既有指派，以時間順序逐筆拍賣全部訂單，
    寫入指派結果並補建 RouteStop（上下車 ETA）。

    ai=true  額外呼叫 Claude 產出 AI 分析摘要。
    reset_scheduled=false  只補排 imported 訂單（增量模式）。
    """
    TW = timezone(timedelta(hours=8))

    # ── 1. Agent 派遣 ─────────────────────────────────────────────────────
    result = agent_dispatcher.run(
        db, service_date,
        dry_run=False,
        reset_scheduled=reset_scheduled,
        late_tolerance_min=late_tolerance_min,
        max_trips_welfare=max_trips_welfare,
        max_trips_normal=max_trips_normal,
    )
    s = result["summary"]
    if s["total"] == 0:
        raise HTTPException(status_code=400, detail="當日無可排班訂單（請先匯入訂單）")

    # ── 2. 取已指派訂單（按車輛、接送時間排序）────────────────────────
    assigned_orders: list[Order] = list(db.scalars(
        select(Order).where(
            Order.service_date == service_date,
            Order.status == "scheduled",
            Order.assigned_vehicle_id.is_not(None),
            Order.pickup_lng.is_not(None),
        ).order_by(Order.assigned_vehicle_id, Order.pickup_time)
    ).all())

    # ── 3. 建 order_id → dropoff_eta 對照表（直接取派遣時計算的值）──
    dropoff_eta_map: dict[int, datetime] = {}
    for item in result.get("assigned", []):
        dt_str = item.get("dropoff_eta")
        if dt_str:
            try:
                dropoff_eta_map[item["order_id"]] = datetime.fromisoformat(dt_str)
            except Exception:
                pass

    # ── 4. 清舊 RouteStop，重建上下車站 ─────────────────────────────
    db.query(RouteStop).filter(RouteStop.service_date == service_date).delete()

    routes_report: dict[int, list[dict]] = {}
    stop_seq: dict[int, int] = {}

    for o in assigned_orders:
        vid = o.assigned_vehicle_id
        pickup_eta = o.pickup_time.astimezone(TW) if o.pickup_time else None
        if pickup_eta is None:
            continue

        # 優先用派遣時的送達時刻；若無則 fallback pickup + 30 min
        dropoff_eta = dropoff_eta_map.get(o.id) or (pickup_eta + timedelta(seconds=1800))

        # RouteStop 上車
        seq_p = stop_seq.get(vid, 0) + 1
        stop_seq[vid] = seq_p
        db.add(RouteStop(
            service_date=service_date, vehicle_id=vid, seq=seq_p, kind="pickup",
            order_id=o.id, lng=o.pickup_lng, lat=o.pickup_lat,
            eta=pickup_eta, address=o.pickup_address,
        ))
        # RouteStop 下車
        seq_d = seq_p + 1
        stop_seq[vid] = seq_d
        db.add(RouteStop(
            service_date=service_date, vehicle_id=vid, seq=seq_d, kind="delivery",
            order_id=o.id, lng=o.dropoff_lng, lat=o.dropoff_lat,
            eta=dropoff_eta, address=o.dropoff_address,
        ))

        routes_report.setdefault(vid, []).append({
            "seq": seq_p, "order_id": o.id, "type": "上車",
            "eta": pickup_eta.strftime("%H:%M"), "addr": o.pickup_address,
        })
        routes_report[vid].append({
            "order_id": o.id, "type": "下車",
            "eta": dropoff_eta.strftime("%H:%M"), "addr": o.dropoff_address,
        })

    db.commit()

    # ── 5. 組回傳（相容原 VROOM 格式）──────────────────────────────
    unassigned_ids = [u["order_id"] for u in result.get("unscheduled", [])]
    p2_count = sum(1 for r in result.get("assigned", []) if r.get("pass") == 2)

    response = {
        "service_date":   service_date.isoformat(),
        "provider":       "agent_auction",
        "vehicles_used":  s["vehicles_used"],
        "orders_total":   s["total"],
        "assigned":       s["assigned"],
        "unassigned":     unassigned_ids,
        "routes":         routes_report,
        "total_duration_sec": 0,
        "agent_detail": {
            "pass1_assigned": s["assigned"] - p2_count,
            "pass2_rescued":  p2_count,
            "max_trips_welfare": max_trips_welfare,
            "max_trips_normal":  max_trips_normal,
        },
    }

    if ai:
        response["ai_summary"] = ai_dispatch.analyze_dispatch(response)

    return response


@router.post("/run-vroom")
def run_vroom(service_date: date, ai: bool = False, db: Session = Depends(get_db)):
    """VROOM 最佳化排班（備用；支援共乘、複雜路由）。"""
    result = dispatcher.run_dispatch(db, service_date)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    if ai:
        result["ai_summary"] = ai_dispatch.analyze_dispatch(result)
    return result


@router.get("/export")
def export_dispatch(service_date: date, fleet: str | None = None, layout: str = "single",
                    source: str = "auto", db: Session = Depends(get_db)):
    """匯出某日派遣表(Excel)。fleet 空=全車行;layout=single|per_vehicle;
    source=auto(自動派遣落地,客戶回饋用)|human(人工實際指派)。"""
    data = dispatch_export.build_workbook(
        db, service_date, (fleet or None), per_vehicle=(layout == "per_vehicle"), source=source)
    suffix = "每車表" if layout == "per_vehicle" else "總表"
    stag = "自動" if source == "auto" else "人工"
    name = f"DR_FISH_{stag}派遣_{service_date.isoformat()}_{fleet or '全車行'}_{suffix}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.post("/zone-suggest")
def zone_suggest(order_id: int, service_date: date, db: Session = Depends(get_db)):
    """區域親和建議:同區新單優先推薦給今天已在該區的司機(dry-run,不寫入)。

    硬條件(車種/輪椅、座位)在排名前過濾;時間窗精確可行性由實際排班確認。
    """
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="訂單不存在")
    return zone_affinity.suggest(db, order, service_date)


@router.get("/vehicle-suggest")
def vehicle_suggest(order_id: int, service_date: date | None = None,
                    top_n: int = 6, fleet_scope: str = "own",
                    db: Session = Depends(get_db)):
    """單筆訂單 → 最佳車輛建議(人工排班用,dry-run):真實 OSRM 插入成本 + 可行性排名。

    fleet_scope:own=本車行/同區(預設)、company=全公司、或指定車行名(跨車行支援)。
    採用建議請呼叫 POST /orders/{id}/assign。
    """
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="訂單不存在")
    return vehicle_suggest_svc.suggest_for_order(
        db, order, service_date or order.service_date, top_n=top_n, fleet_scope=fleet_scope)


@router.get("/pool-suggest")
def pool_suggest_day(
    service_date: date, fleet: str, window_min: int = 30,
    max_detour_min: float = 15.0, db: Session = Depends(get_db),
):
    """共乘推薦(單日):雙跑 VROOM 找出值得徵詢同意的共乘組 + 可省車數(dry-run)。"""
    r = pool_suggest.suggest_day(db, fleet, service_date, window_min, max_detour_min)
    if r is None:
        raise HTTPException(status_code=404, detail="該日該車行無成行單或無可用車")
    return r


@router.get("/demand-forecast")
def demand_forecast(fleet: str | None = None, horizon_days: int = 14,
                    lookback_weeks: int = 8, db: Session = Depends(get_db)):
    """輕量需求預測(weekday 基線):未來各日趟次 + 建議排車數,供班表/人力規劃。"""
    return forecast.forecast(db, fleet, horizon_days, lookback_weeks)


@router.get("/driver-suggest")
def driver_suggest(passenger: str, min_trips: int = 5, min_ratio: float = 0.5,
                   db: Session = Depends(get_db)):
    """常客固定駕駛建議:單一乘客的慣用駕駛排行 + 是否達高信心(軟性偏好,供人工指派參考)。"""
    return driver_affinity.suggest(db, passenger, min_trips, min_ratio)


@router.get("/driver-loyalty")
def driver_loyalty(min_trips: int = 5, min_ratio: float = 0.5, db: Session = Depends(get_db)):
    """高忠誠乘客清單(集中度達門檻):適合排班優先沿用慣用駕駛。"""
    return driver_affinity.loyal_passengers(db, min_trips, min_ratio)


@router.get("/pool-gain")
def pool_gain(db: Session = Depends(get_db)):
    """共乘增益總覽(讀 pool_projection):現況車日 → 推薦組全同意後車日 + 額外省幅。"""
    rows = list(db.scalars(select(PoolProjection).order_by(PoolProjection.fleet)).all())
    by_fleet = {}
    g_now = g_pool = g_saved = g_ask = g_days = 0
    for r in rows:
        by_fleet[r.fleet] = {
            "days": r.days, "v_now": r.v_now, "v_pool": r.v_pool,
            "saved_vehicles": r.saved_vehicles, "ask_groups": r.ask_groups,
            "extra_saved_pct_vs_now": round(100 * r.saved_vehicles / r.v_now, 1) if r.v_now else 0,
        }
        g_now += r.v_now; g_pool += r.v_pool; g_saved += r.saved_vehicles
        g_ask += r.ask_groups; g_days = max(g_days, r.days)
    recurring = recurring_pairs.find(db, min_days=3)["pairs_found"]
    return {
        "available": bool(rows),
        "group": {
            "v_now": g_now, "v_pool": g_pool, "saved_vehicles": g_saved,
            "ask_groups": g_ask,
            "extra_saved_pct_vs_now": round(100 * g_saved / g_now, 1) if g_now else 0,
            "recurring_pairs": recurring,
        },
        "by_fleet": by_fleet,
    }


@router.get("/pool-recurring")
def pool_recurring(min_days: int = 3, time_tol_min: int = 30,
                   near_m: float = 1500.0, db: Session = Depends(get_db)):
    """常態共乘對:反覆同時間/同起訖點同行的乘客對,值得一次徵長期同意(dry-run)。"""
    return recurring_pairs.find(db, min_days, time_tol_min, near_m)


class PoolConsentIn(BaseModel):
    order_ids: list[int]
    consent: bool = True


@router.post("/pool-consent")
def pool_consent(
    body: PoolConsentIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """登錄共乘同意/撤回(留痕:誰、何時)。同意後排班/對比/推薦會自動納入共乘。"""
    orders = list(db.scalars(select(Order).where(Order.id.in_(body.order_ids))).all())
    if not orders:
        raise HTTPException(status_code=404, detail="找不到指定訂單")
    now = datetime.now(timezone.utc)
    for o in orders:
        o.allow_pool = body.consent
        o.pool_consent_at = now if body.consent else None
        o.pool_consent_by = current.username if body.consent else None
    db.commit()
    return {"updated": len(orders), "consent": body.consent, "by": current.username}


class AssistantMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class AssistantIn(BaseModel):
    messages: list[AssistantMessage]


@router.post("/assistant")
def dispatch_assistant(body: AssistantIn, db: Session = Depends(get_db)):
    """調度員 AI 助理(對話 + Claude tool-use,唯讀查詢真實資料後給建議)。"""
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="最後一則訊息需為使用者發言")
    return assistant.chat(db, msgs)


@router.post("/ai-analyze")
def ai_analyze(service_date: date, db: Session = Depends(get_db)):
    """對最近一次排班結果（已存於 DB）呼叫 AI 分析，不重新排班。"""
    from sqlalchemy import select as sa_select
    from app.models.vehicle import Vehicle

    orders_dispatched = list(db.scalars(
        sa_select(Order)
        .where(Order.service_date == service_date, Order.status == "scheduled")
    ).all())
    orders_unassigned = list(db.scalars(
        sa_select(Order)
        .where(Order.service_date == service_date, Order.status == "imported")
        .where(Order.pickup_lng.is_not(None))
    ).all())

    if not orders_dispatched and not orders_unassigned:
        raise HTTPException(status_code=404, detail="該日無排班資料")

    # 組 routes dict（簡化版）
    routes: dict = {}
    for o in orders_dispatched:
        vid = str(o.assigned_vehicle_id)
        routes.setdefault(vid, [])
        routes[vid].append({
            "order_id": o.id, "type": "上車",
            "eta": o.eta.strftime("%H:%M") if o.eta else "--",
        })

    pseudo_result = {
        "service_date": service_date.isoformat(),
        "vehicles_used": len(routes),
        "orders_total": len(orders_dispatched) + len(orders_unassigned),
        "assigned": len(orders_dispatched),
        "unassigned": [o.id for o in orders_unassigned],
        "skipped_no_coords": [],
        "total_duration_sec": 0,
        "routes": routes,
    }
    summary = ai_dispatch.analyze_dispatch(pseudo_result)
    return {"service_date": service_date.isoformat(), "ai_summary": summary}


@router.post("/ai-insert")
def ai_insert_eval(
    order_id: int,
    service_date: date,
    db: Session = Depends(get_db),
):
    """評估將指定訂單插入現有排班哪台車最合適（AI 建議）。"""
    from sqlalchemy import select as sa_select

    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="訂單不存在")

    dispatched = list(db.scalars(
        sa_select(Order)
        .where(Order.service_date == service_date, Order.status == "scheduled")
    ).all())

    routes: dict = {}
    for o in dispatched:
        vid = str(o.assigned_vehicle_id)
        routes.setdefault(vid, [])
        routes[vid].append({
            "order_id": o.id, "type": "上車",
            "eta": o.eta.strftime("%H:%M") if o.eta else "--",
        })

    new_order_info = {
        "pickup_address": order.pickup_address,
        "dropoff_address": order.dropoff_address,
        "pickup_time": str(order.pickup_time),
        "vehicle_type": order.vehicle_type,
        "pax": order.pax,
        "need_wheelchair": order.need_wheelchair,
    }
    suggestion = ai_dispatch.evaluate_insertion(new_order_info, routes)
    return {"order_id": order_id, "ai_suggestion": suggestion}


@router.get("/comparison/summary")
def comparison_summary(db: Session = Depends(get_db)):
    """人工 vs 自動 對比總覽(各車行 + 集團)。"""
    def agg(where=None):
        q = select(
            func.count(), func.sum(DispatchComparison.n_orders),
            func.sum(DispatchComparison.human_vehicles),
            func.sum(DispatchComparison.vroom_vehicles),
            func.sum(DispatchComparison.saved_vehicles),
            func.sum(DispatchComparison.vroom_unassigned),
            func.count().filter(DispatchComparison.saved_vehicles > 0),
        )
        if where is not None:
            q = q.where(where)
        days, orders, hv, vv, saved, unassigned, win_days = db.execute(q).one()
        return {
            "days": days or 0, "orders": int(orders or 0),
            "human_vehicle_days": int(hv or 0), "vroom_vehicle_days": int(vv or 0),
            "saved_vehicle_days": int(saved or 0),
            "vroom_unassigned": int(unassigned or 0),
            "days_vroom_better": win_days or 0,
            "saved_pct": round(100.0 * (saved or 0) / hv, 1) if hv else 0,
        }

    by_fleet = {}
    for (f,) in db.execute(select(DispatchComparison.fleet.distinct())).all():
        by_fleet[f] = agg(DispatchComparison.fleet == f)
    return {"group": agg(), "by_fleet": by_fleet}


@router.get("/comparison/savings")
def comparison_savings(db: Session = Depends(get_db)):
    """把省下的車日換算成 NT$(實測期間 + 年化),供車隊報價/ROI 試算。

    成本參數讀自「參數設定」:cost_per_vehicle_day(每車日成本)、annual_service_days(年營運天數)。
    """
    cost = float(app_settings.get(db, "cost_per_vehicle_day", 2500) or 0)
    annual_days = int(app_settings.get(db, "annual_service_days", 300) or 0)

    def agg(where=None):
        q = select(
            func.count(func.distinct(DispatchComparison.service_date)),
            func.coalesce(func.sum(DispatchComparison.human_vehicles), 0),
            func.coalesce(func.sum(DispatchComparison.saved_vehicles), 0),
        )
        if where is not None:
            q = q.where(where)
        obs_days, human_vd, saved_vd = db.execute(q).one()
        obs_days = obs_days or 0
        human_vd = int(human_vd or 0)
        saved_vd = int(saved_vd or 0)
        observed_saving = saved_vd * cost
        # 年化:以實測期間的「每營運日平均省車日」外推到全年營運天數
        per_day_saving = (observed_saving / obs_days) if obs_days else 0.0
        annual_saving = per_day_saving * annual_days
        return {
            "observed_days": obs_days,
            "saved_vehicle_days": saved_vd,
            "human_vehicle_days": human_vd,
            "observed_saving_ntd": round(observed_saving),
            "per_day_saving_ntd": round(per_day_saving),
            "annual_saving_ntd": round(annual_saving),
        }

    by_fleet = {}
    for (f,) in db.execute(select(DispatchComparison.fleet.distinct())).all():
        by_fleet[f] = agg(DispatchComparison.fleet == f)
    return {
        "cost_per_vehicle_day": cost,
        "annual_service_days": annual_days,
        "group": agg(),
        "by_fleet": by_fleet,
    }


@router.get("/comparison/sensitivity")
def comparison_sensitivity(
    windows: str = "15,30,45,60", fleet: str | None = None,
    sample_days: int = 20, db: Session = Depends(get_db),
):
    """時間窗敏感度:多個上車時間窗下重跑取樣日,看「放寬時間窗 → 省更多車 vs 未派」權衡。

    windows 為逗號分隔分鐘數;取樣自最忙的 sample_days 天(各 window 同基準)。
    """
    try:
        wins = [int(w) for w in windows.split(",") if w.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="windows 需為逗號分隔的整數分鐘")
    if not wins:
        raise HTTPException(status_code=400, detail="請至少提供一個時間窗")
    return comparison.sensitivity(db, wins, fleet, sample_days)


@router.get("/comparison")
def comparison_list(fleet: str | None = None, date_from: date | None = None,
                    date_to: date | None = None, limit: int = 500,
                    db: Session = Depends(get_db)):
    """逐日對比明細(可選車行 + 日期區間)。"""
    q = select(DispatchComparison).order_by(
        DispatchComparison.service_date, DispatchComparison.fleet
    )
    if fleet:
        q = q.where(DispatchComparison.fleet == fleet)
    if date_from:
        q = q.where(DispatchComparison.service_date >= date_from)
    if date_to:
        q = q.where(DispatchComparison.service_date <= date_to)
    rows = list(db.scalars(q.limit(limit)).all())
    return [
        {
            "fleet": r.fleet, "service_date": r.service_date.isoformat(),
            "n_orders": r.n_orders, "human_vehicles": r.human_vehicles,
            "vroom_vehicles": r.vroom_vehicles, "saved_vehicles": r.saved_vehicles,
            "vroom_unassigned": r.vroom_unassigned,
            "human_distance_km": round((r.human_distance_m or 0) / 1000, 1),
            "vroom_drive_min": round((r.vroom_drive_sec or 0) / 60),
        }
        for r in rows
    ]


@router.post("/comparison/persist-day")
def comparison_persist_day(service_date: date,
                           source: str = "run",
                           db: Session = Depends(get_db)):
    """把某日派遣結果落地至 auto_dispatch_stop / dispatch_comparison / unassigned_record。

    source=run（預設）：從 run_dispatch 已寫入的 route_stop+orders 建立，
                        不重跑 VROOM，看板顯示與實際派遣完全一致（建議用法）。
    source=vroom：重新跑 VROOM 對比分析（原行為，適合獨立比對研究）。
    """
    if source == "run":
        return comparison.persist_day_from_run(db, service_date)
    return comparison.persist_day(db, service_date)


@router.get("/auto-stops")
def auto_stops(service_date: date, fleet: str | None = None, plate: str | None = None,
               db: Session = Depends(get_db)):
    """讀取某日已落地的自動派遣停靠明細(每車每上/下車點 + ETA + 在車人數 + 是否支援)。"""
    from app.models.auto_dispatch_stop import AutoDispatchStop
    q = select(AutoDispatchStop).where(AutoDispatchStop.service_date == service_date)
    if fleet:
        q = q.where(AutoDispatchStop.fleet == fleet)
    if plate:
        q = q.where(AutoDispatchStop.plate == plate)
    rows = list(db.scalars(q.order_by(
        AutoDispatchStop.fleet, AutoDispatchStop.vehicle_id, AutoDispatchStop.seq)).all())
    oids = [r.order_id for r in rows if r.order_id]
    omap = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_(oids))).all()} if oids else {}
    TW = timezone(timedelta(hours=8))
    items = []
    for r in rows:
        o = omap.get(r.order_id)
        items.append({
            "fleet": r.fleet, "vehicle_id": r.vehicle_id, "plate": r.plate,
            "seq": r.seq, "kind": r.kind, "order_id": r.order_id,
            "passenger": o.passenger_name if o else None,
            "address": (o.pickup_address if r.kind == "pickup" else o.dropoff_address) if o else None,
            "eta": r.eta.astimezone(TW).strftime("%H:%M") if r.eta else None,
            "occupancy": r.occupancy, "is_support": r.is_support,
        })
    return {"service_date": service_date.isoformat(), "count": len(items),
            "run_at": rows[0].run_at.isoformat() if rows and rows[0].run_at else None,
            "items": items}


@router.get("/calibration")
def calibration_view(db: Session = Depends(get_db)):
    """每趟作業時間/速度的歷史校準:回傳目前已套用值 + 重新分析的建議值。"""
    applied = [
        {"fleet": r.fleet, "service_normal_min": round(r.service_normal_sec / 60, 1),
         "service_welfare_min": round(r.service_welfare_sec / 60, 1),
         "speed_factor": r.speed_factor, "samples": r.samples}
        for r in db.scalars(select(FleetCalibration).order_by(FleetCalibration.fleet)).all()
    ]
    return {"applied": applied, "recommendation": calibration.analyze(db)}


@router.post("/calibration/apply")
def calibration_apply(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """重新從歷史校準每趟作業時間/速度,寫入 fleet_calibration(限登入)。"""
    return calibration.apply(db)


@router.get("/comparison/available-days")
def comparison_available_days(db: Session = Depends(get_db)):
    """可做逐車對比的(車行,日期):有成行單(done+座標)且有人工派遣紀錄(R 牌、已轉正式單)。
    不依賴對比批次,匯入班表後當日即可選。
    """
    has_human = (
        select(DispatchHistory.id)
        .where(
            DispatchHistory.fleet == Order.fleet,
            DispatchHistory.service_date == Order.service_date,
            DispatchHistory.status == "已轉至正式單",
            DispatchHistory.plate.like("R%"),
        )
        .exists()
    )
    rows = db.execute(
        select(Order.fleet, Order.service_date, func.count())
        .where(Order.status == "done", Order.pickup_lng.is_not(None), has_human)
        .group_by(Order.fleet, Order.service_date)
        .order_by(Order.service_date.desc(), Order.fleet)
    ).all()
    return [
        {"fleet": f, "service_date": sd.isoformat(), "n_orders": n}
        for f, sd, n in rows
    ]


@router.get("/comparison/by-vehicle")
def comparison_by_vehicle(
    fleet: str,
    service_date: date,
    window_min: int | None = None,   # None=用系統 pickup_window_min(與看板/落地一致)
    db: Session = Depends(get_db),
):
    """逐車對比:某車行某日,左=人工實際派遣、右=VROOM 自動派遣(同一車隊池)。
    回傳每車並排趟次(標出換車的趟)+ 每車總行駛里程與工作時間。
    """
    r = comparison.compare_day_by_vehicle(db, fleet, service_date, window_min)
    if r is None:
        raise HTTPException(404, "當日無成行單或查無人工派遣紀錄")
    return r


@router.get("/comparison/export")
def comparison_export_range(date_from: date, date_to: date, fleet: str | None = None,
                            db: Session = Depends(get_db)):
    """匯出某日期區間的人工 vs 自動比對(Excel:逐日總覽 + 各車行日)。"""
    data = comparison_export.summary_workbook(db, date_from, date_to, fleet or None)
    name = f"DR_FISH_比對_{date_from.isoformat()}_{date_to.isoformat()}_{fleet or '全車行'}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.get("/comparison/by-vehicle/export")
def comparison_by_vehicle_export(fleet: str, service_date: date, window_min: int | None = None,
                                 db: Session = Depends(get_db)):
    """匯出某日某車行的逐車對比明細(Excel)。"""
    data = comparison_export.by_vehicle_workbook(db, fleet, service_date, window_min)
    name = f"DR_FISH_逐車對比_{service_date.isoformat()}_{fleet}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.get("/osrm-health")
def osrm_health():
    """探測自架 OSRM 是否就緒。"""
    return {"osrm_url": settings.OSRM_URL, "ready": osrm.health()}


@router.get("/routes-geojson")
def routes_geojson(service_date: date, db: Session = Depends(get_db)):
    """把某日各車的排班路線轉為 GeoJSON(每車一條 OSRM 實際路線 + 停靠點)。"""
    stops = list(
        db.scalars(
            select(RouteStop)
            .where(RouteStop.service_date == service_date)
            .order_by(RouteStop.vehicle_id, RouteStop.seq)
        ).all()
    )
    if not stops:
        return {"type": "FeatureCollection", "features": [], "vehicles": []}

    by_vehicle: dict[int, list[RouteStop]] = {}
    for s in stops:
        by_vehicle.setdefault(s.vehicle_id, []).append(s)

    features = []
    vehicles_meta = []
    for i, (vid, vstops) in enumerate(by_vehicle.items()):
        color = _COLORS[i % len(_COLORS)]
        vehicles_meta.append({"vehicle_id": vid, "color": color, "stops": len(vstops)})
        pts = [(s.lng, s.lat) for s in vstops if s.lng is not None]

        # 路線 LineString(OSRM 實際道路;失敗則退化為直線)
        geom = None
        try:
            r = osrm.route_geometry(pts)
            if r:
                geom = r["geometry"]
        except Exception:  # noqa: BLE001
            geom = None
        if geom is None and len(pts) >= 2:
            geom = {"type": "LineString", "coordinates": [[lng, lat] for lng, lat in pts]}
        if geom:
            features.append({
                "type": "Feature",
                "properties": {"vehicle_id": vid, "color": color, "kind": "route"},
                "geometry": geom,
            })

        # 停靠點 Point
        for s in vstops:
            if s.lng is None:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "vehicle_id": vid, "color": color, "kind": s.kind,
                    "seq": s.seq, "order_id": s.order_id,
                    "eta": s.eta.strftime("%H:%M") if s.eta else None,
                    "address": s.address,
                },
                "geometry": {"type": "Point", "coordinates": [s.lng, s.lat]},
            })

    return {"type": "FeatureCollection", "features": features, "vehicles": vehicles_meta}


@router.get("/matrix")
def matrix_preview(service_date: date, db: Session = Depends(get_db)):
    """用某日已地理編碼訂單的上/下車點,實際建一份行車時間矩陣以驗證引擎。"""
    stmt = (
        select(Order)
        .where(Order.service_date == service_date)
        .where(Order.pickup_lng.is_not(None), Order.dropoff_lng.is_not(None))
        .order_by(Order.id)
    )
    orders = list(db.scalars(stmt).all())
    if not orders:
        raise HTTPException(status_code=404, detail="該日沒有已地理編碼的訂單")

    # 收集點位(去重),記錄標籤供回傳檢視
    points: list[tuple[float, float]] = []
    labels: list[str] = []
    for o in orders:
        for kind, lng, lat in (
            ("上", o.pickup_lng, o.pickup_lat),
            ("下", o.dropoff_lng, o.dropoff_lat),
        ):
            pt = (round(lng, 6), round(lat, 6))
            if pt not in points:
                points.append(pt)
                labels.append(f"#{o.id}{kind}")

    try:
        result = matrix.build_matrix(points)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"矩陣計算失敗:{e}")

    durations = result["durations"]
    return {
        "provider": result["provider"],
        "n_points": len(points),
        "labels": labels,
        "durations_sec": durations,
        "sample": {
            "from": labels[0],
            "to": labels[1] if len(labels) > 1 else labels[0],
            "duration_sec": durations[0][1] if len(durations) > 1 else 0,
            "distance_m": (result.get("distances") or [[None, None]])[0][1],
        },
    }


_DT_SERVED = "已轉至正式單"

# ---- 未派分析:原因標籤 + 行控回饋類別 ----
_REASON_LABEL = {
    "out_of_hours": "服務時段外(06:00–18:00 之外)",
    "no_welfare": "無福祉車可用",
    "unroutable": "地址/座標無法路由",
    "suspect_geocode": "座標離營運區過遠(疑地理編碼錯誤)",
    "fleet_saturated": "全車隊滿載(需增車)",
    "solver_margin": "求解邊際(常為固定趟緊窗趕不到;放寬上車窗或校正起點可排入)",
    "infeasible": "車隊已滿載 / 時間窗無法排入",   # 舊碼,相容歷史紀錄
}
_FEEDBACK_CATS = [
    "司機可加班補位", "客戶可調整時間", "實際可共乘",
    "地址或座標有誤", "確實無法服務(需外援)", "其他",
]


@router.get("/unassigned/feedback-categories")
def unassigned_feedback_categories():
    """行控回饋可選類別 + 系統原因標籤(供前端下拉與顯示)。"""
    return {"categories": _FEEDBACK_CATS, "reasons": _REASON_LABEL}


@router.get("/unassigned/insights")
def unassigned_insights(fleet: str | None = None, ai: bool = True,
                        db: Session = Depends(get_db)):
    """未派回饋學習建議:統計未派原因 × 行控回饋 → 改善行動(可選 Claude 白話診斷)。"""
    from app.services import unassigned_insights as ui
    return ui.insights(db, fleet, use_ai=ai)


@router.get("/unassigned/dates")
def unassigned_dates(fleet: str | None = None, db: Session = Depends(get_db)):
    """各日未派訂單數(供管理者點選日期),含已回饋數。"""
    q = select(
        UnassignedRecord.service_date, func.count(),
        func.count().filter(UnassignedRecord.feedback_category.is_not(None)),
    )
    if fleet:
        q = q.where(UnassignedRecord.fleet == fleet)
    rows = db.execute(
        q.group_by(UnassignedRecord.service_date)
        .order_by(UnassignedRecord.service_date.desc())
    ).all()
    return [{"service_date": d.isoformat(), "count": c, "feedback_count": fc}
            for d, c, fc in rows]


@router.get("/unassigned")
def unassigned_list(service_date: date, fleet: str | None = None, db: Session = Depends(get_db)):
    """某日未派訂單清單(含原因 + 人工派遣車 + 是否已回饋)。"""
    q = select(UnassignedRecord).where(UnassignedRecord.service_date == service_date)
    if fleet:
        q = q.where(UnassignedRecord.fleet == fleet)
    recs = list(db.scalars(q.order_by(UnassignedRecord.fleet, UnassignedRecord.id)).all())
    omap = {}
    oids = [r.order_id for r in recs if r.order_id]
    if oids:
        omap = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_(oids))).all()}
    items = []
    for r in recs:
        o = omap.get(r.order_id)
        items.append({
            "id": r.id, "fleet": r.fleet,
            "order_id": r.order_id,
            "order_status": o.status if o else None,   # imported/scheduled=營運中可立即指派;done=僅唯讀建議
            "reason_code": r.reason_code, "reason_label": _REASON_LABEL.get(r.reason_code, r.reason_code),
            "human_plate": r.human_plate, "human_driver": r.human_driver,
            "pickup_time": o.pickup_time.strftime("%H:%M") if o and o.pickup_time else None,
            "passenger": o.passenger_name if o else None,
            "pickup": o.pickup_address if o else None,
            "dropoff": o.dropoff_address if o else None,
            "pax": o.pax if o else None,
            "welfare": bool(o and (o.vehicle_type == "welfare" or o.need_wheelchair)) if o else False,
            "has_feedback": r.feedback_category is not None,
            "feedback_category": r.feedback_category,
        })
    return {"service_date": service_date.isoformat(), "fleet": fleet,
            "count": len(items), "items": items}


@router.get("/unassigned/{rid}")
def unassigned_detail(rid: int, db: Session = Depends(get_db)):
    """單筆未派明細:系統原因 + 人工派遣車/駕駛 + 訂單資訊 + 現有行控回饋。"""
    r = db.get(UnassignedRecord, rid)
    if r is None:
        raise HTTPException(status_code=404, detail="找不到該未派記錄")
    o = db.get(Order, r.order_id) if r.order_id else None
    return {
        "id": r.id, "service_date": r.service_date.isoformat(), "fleet": r.fleet,
        "reason_code": r.reason_code, "reason_label": _REASON_LABEL.get(r.reason_code, r.reason_code),
        "reason_detail": r.reason_detail, "window_min": r.window_min,
        "human_plate": r.human_plate, "human_driver": r.human_driver,
        "order": {
            "source_order_no": r.source_order_no,
            "pickup_time": o.pickup_time.strftime("%Y-%m-%d %H:%M") if o and o.pickup_time else None,
            "passenger": o.passenger_name if o else None,
            "passenger_phone": o.passenger_phone if o else None,
            "pickup": o.pickup_address if o else None,
            "dropoff": o.dropoff_address if o else None,
            "pax": o.pax if o else None,
            "vehicle_type": o.vehicle_type if o else None,
            "need_wheelchair": o.need_wheelchair if o else None,
        } if o else None,
        "feedback": {
            "category": r.feedback_category, "note": r.feedback_note,
            "by": r.feedback_by,
            "at": r.feedback_at.isoformat() if r.feedback_at else None,
        },
    }


class UnassignedFeedbackIn(BaseModel):
    category: str
    note: str | None = None


@router.post("/unassigned/{rid}/feedback")
def unassigned_feedback(rid: int, body: UnassignedFeedbackIn,
                        db: Session = Depends(get_db),
                        current: User = Depends(get_current_user)):
    """行控填入未派因素(協助系統學習):記錄類別、說明、填寫人與時間。"""
    r = db.get(UnassignedRecord, rid)
    if r is None:
        raise HTTPException(status_code=404, detail="找不到該未派記錄")
    r.feedback_category = body.category
    r.feedback_note = body.note
    r.feedback_by = current.username
    r.feedback_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": r.id, "feedback_category": r.feedback_category, "by": r.feedback_by}


@router.post("/assign-unscheduled")
def assign_unscheduled(
    service_date: date,
    max_detour_km: float = 15.0,
    late_tolerance_min: int = 10,
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """未排班訂單自動指派。
    依車種相容＋鄰近地理位置逐一分配，寫回 assigned_vehicle_id + status=scheduled。
    late_tolerance_min：允許遲到幾分鐘（預設 10 分）。
    dry_run=true 時只回傳計畫、不寫入 DB。
    """
    return unscheduled_assigner.assign(
        db, service_date,
        max_detour_km=max_detour_km,
        late_tolerance_min=late_tolerance_min,
        dry_run=dry_run,
    )


@router.get("/validate-schedule")
def validate_schedule(service_date: date, db: Session = Depends(get_db)):
    """排班合理性檢查。
    回傳當日各車的時間重疊（overlap）與往返緊接（roundtrip）衝突清單。
    同起同終的共乘趟次不列入。
    """
    return schedule_validator.validate(db, service_date)


@router.post("/resolve-conflicts")
def resolve_conflicts(
    service_date: date,
    late_tolerance_min: int = 10,
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """衝突剔除 + 補排。
    1. 執行 validate-schedule 取衝突清單。
    2. 每個衝突對的後趟（nxt）改回 imported。
    3. 對剔除訂單執行 assign-unscheduled 貪婪補排。
    late_tolerance_min：允許遲到幾分鐘（預設 10 分）。
    dry_run=true 時模擬但不寫 DB。
    """
    return conflict_resolver.resolve(
        db, service_date,
        late_tolerance_min=late_tolerance_min,
        dry_run=dry_run,
    )


@router.get("/board")
def dispatch_board_view(service_date: date, source: str = "human",
                        db: Session = Depends(get_db)):
    """派遣看板:某日各車趟次(含時間衝突)+ 未指派欄。
    source=human(orders 當前指派,可拖放微調)| auto(自動派遣落地,唯讀)。"""
    from app.services import dispatch_board as board_svc
    return board_svc.board(db, service_date, source=source)


@router.post("/board/reassign")
def board_reassign(payload: dict, db: Session = Depends(get_db)):
    """統一重指派端點：order_id + vehicle_id(None=移至未指派) + service_date。"""
    order_id = payload.get("order_id")
    vehicle_id = payload.get("vehicle_id")  # None = 移至未指派
    o = db.get(Order, order_id)
    if not o:
        from fastapi import HTTPException
        raise HTTPException(404, "訂單不存在")
    if vehicle_id:
        o.assigned_vehicle_id = vehicle_id
        if o.status == "imported":
            o.status = "scheduled"
    else:
        o.assigned_vehicle_id = None
        if o.status in ("scheduled",):
            o.status = "imported"
    db.commit()
    return {"ok": True, "order_id": order_id, "vehicle_id": vehicle_id}


@router.get("/board/meta")
def board_meta(db: Session = Depends(get_db)):
    """看板預設日期:回最近「有派車(已指派訂單)」的日期,供前端一進來就有資料。"""
    latest = db.scalar(select(func.max(Order.service_date)).where(
        Order.assigned_vehicle_id.is_not(None)))
    return {"latest_date": latest.isoformat() if latest else None}


@router.get("/daily-tasks/meta")
def daily_tasks_meta(db: Session = Depends(get_db)):
    """口卡查詢的過濾選項:資料日期範圍 + 車行清單(供前端預設日期與下拉)。"""
    mn, mx = db.execute(
        select(func.min(DispatchHistory.service_date), func.max(DispatchHistory.service_date))
        .where(DispatchHistory.status == _DT_SERVED)
    ).one()
    fleets = [f for (f,) in db.execute(
        select(DispatchHistory.fleet.distinct())
        .where(DispatchHistory.fleet.is_not(None)).order_by(DispatchHistory.fleet)
    ).all()]
    return {"min_date": mn.isoformat() if mn else None,
            "max_date": mx.isoformat() if mx else None, "fleets": fleets}


def _plan_drv_by_veh(db: Session, service_date: date) -> dict:
    """車 → (司機名, 電話);Driver.vehicle_id 為底,當日 DriverVehicleAssignment 覆寫。"""
    out: dict[int, tuple] = {}
    for d in db.scalars(select(Driver).where(Driver.vehicle_id.is_not(None))).all():
        out.setdefault(d.vehicle_id, (d.name, d.phone))
    for a in db.scalars(select(DriverVehicleAssignment).where(
            DriverVehicleAssignment.service_date == service_date)).all():
        dn = db.get(Driver, a.driver_id)
        if dn:
            out[a.vehicle_id] = (dn.name, dn.phone)
    return out


def _plan_order_task(o: Order) -> dict:
    src = (o.booking_source or "").strip()
    is_standby = "候補" in src
    return {
        "time": o.pickup_time.strftime("%H:%M") if o.pickup_time else "--:--",
        "passenger": o.passenger_name, "phone": o.passenger_phone,
        "pickup": o.pickup_address, "dropoff": o.dropoff_address,
        "pickup_town": None, "dropoff_town": None,
        "pax": o.pax or 1, "wheelchair": 1 if o.need_wheelchair else 0,
        "welfare": o.vehicle_type == "welfare" or bool(o.need_wheelchair),
        "est_min": None, "order_no": o.source_order_no, "status": o.status,
        "fleet": o.fleet,
        "support_fleet": o.support_fleet if (o.support_fleet and o.support_fleet != o.fleet) else None,
        "is_standby": is_standby,     # 候補訂單標記
        "booking_source": o.booking_source,
    }


def _plan_cards_response(grouped: dict, service_date: date, fleet, plate, total_tasks, source):
    fleets_out = []
    for fl, vehs in sorted(grouped.items()):
        vlist = []
        for pl in sorted(vehs):
            v = vehs[pl]
            v["tasks"].sort(key=lambda t: t["time"])
            v["task_count"] = len(v["tasks"])
            v["first"] = v["tasks"][0]["time"] if v["tasks"] else "--:--"
            v["last"] = v["tasks"][-1]["time"] if v["tasks"] else "--:--"
            vlist.append(v)
        fleets_out.append({"fleet": fl, "vehicles": vlist, "vehicle_count": len(vlist),
                           "task_count": sum(v["task_count"] for v in vlist)})
    return {
        "service_date": service_date.isoformat(), "fleet": fleet, "plate": plate, "source": source,
        "total_vehicles": sum(f["vehicle_count"] for f in fleets_out),
        "total_tasks": total_tasks,
        "fleets": fleets_out,
    }


def _daily_tasks_plan(db: Session, service_date: date, fleet: str | None, plate: str | None):
    """口卡(系統派遣版)。

    - 即時(未來日已跑過排班):有 scheduled/ongoing 訂單 → 讀 orders.assigned_vehicle_id。
    - 歷史日(全為 done):用 VROOM 即時算「系統最佳化後」的每車每趟(read-only,不寫入)。
    """
    live = db.scalar(select(func.count()).select_from(Order).where(
        Order.service_date == service_date,
        Order.status.in_(["scheduled", "ongoing"]),
        Order.assigned_vehicle_id.is_not(None))) or 0
    if live:
        return _plan_from_assigned(db, service_date, fleet, plate)
    return _plan_from_compute(db, service_date, fleet, plate)


def _plan_from_assigned(db: Session, service_date: date, fleet: str | None, plate: str | None):
    drv = _plan_drv_by_veh(db, service_date)
    q = select(Order).where(
        Order.service_date == service_date,
        Order.assigned_vehicle_id.is_not(None),
        Order.status.in_(["scheduled", "ongoing", "done"]),
    )
    if fleet:
        q = q.where(Order.fleet == fleet)
    orders = list(db.scalars(q.order_by(Order.assigned_vehicle_id, Order.pickup_time)).all())
    veh_ids = {o.assigned_vehicle_id for o in orders}
    vmap = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(veh_ids))).all()} if veh_ids else {}
    if plate:
        keep = {vid for vid, v in vmap.items() if v.plate == plate}
        orders = [o for o in orders if o.assigned_vehicle_id in keep]
    grouped: dict[str, dict[str, dict]] = {}
    for o in orders:
        v = vmap.get(o.assigned_vehicle_id)
        plate_str = v.plate if v else f"#{o.assigned_vehicle_id}"
        fl = o.fleet or (v.home_fleet if v else None) or "(未標車行)"
        name, phone = drv.get(o.assigned_vehicle_id, (None, None))
        grouped.setdefault(fl, {}).setdefault(
            plate_str, {"plate": plate_str, "driver": name, "driver_phone": phone, "tasks": []}
        )["tasks"].append(_plan_order_task(o))
    return _plan_cards_response(grouped, service_date, fleet, plate, len(orders), "plan")


def _plan_from_compute(db: Session, service_date: date, fleet: str | None, plate: str | None):
    """歷史日:對每個車行用 VROOM 算系統最佳化派遣,組成口卡(read-only)。"""
    drv = _plan_drv_by_veh(db, service_date)
    if fleet:
        fleets = [fleet]
    else:
        fleets = [f for (f,) in db.execute(select(Order.fleet.distinct()).where(
            Order.service_date == service_date, Order.status == "done")).all() if f]

    plan_by_fleet: dict[str, dict] = {}   # fl -> {vid: [oid,...]}
    all_oids: list[int] = []
    for fl in fleets:
        r = comparison.compare_day(db, fl, service_date, return_plan=True)
        if r and r.get("plan"):
            plan_by_fleet[fl] = r["plan"]
            for oids in r["plan"].values():
                all_oids += oids
    omap = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_(all_oids))).all()} if all_oids else {}
    vids = {vid for p in plan_by_fleet.values() for vid in p}
    vmap = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(vids))).all()} if vids else {}

    grouped: dict[str, dict[str, dict]] = {}
    total = 0
    for fl, plan in plan_by_fleet.items():
        for vid, oids in plan.items():
            v = vmap.get(vid)
            plate_str = v.plate if v else f"#{vid}"
            if plate and plate_str != plate:
                continue
            name, phone = drv.get(vid, (None, None))
            tasks = [_plan_order_task(omap[oid]) for oid in oids if oid in omap]
            total += len(tasks)
            grouped.setdefault(fl, {})[plate_str] = {
                "plate": plate_str, "driver": name, "driver_phone": phone, "tasks": tasks}
    return _plan_cards_response(grouped, service_date, fleet, plate, total, "plan-compute")


@router.get("/daily-tasks")
def daily_tasks(service_date: date, fleet: str | None = None, plate: str | None = None,
                source: str = "history", db: Session = Depends(get_db)):
    """每日車輛任務清單(口卡):依車行 → 每台車 → 依上車時間排序的任務。

    source:
      - history(預設):人工派遣紀錄(dispatch_history,僅成行)。
      - plan:系統當前指派(orders.assigned_vehicle_id;含未來自動排班日)。
    乘客姓名/電話由訂單關聯。可依日期(必填)、車行、車牌過濾。
    """
    if source == "plan":
        return _daily_tasks_plan(db, service_date, fleet, plate)
    q = (
        select(DispatchHistory)
        .where(DispatchHistory.service_date == service_date,
               DispatchHistory.status == _DT_SERVED,
               DispatchHistory.plate.like("R%"))
    )
    if fleet:
        q = q.where(DispatchHistory.fleet == fleet)
    if plate:
        q = q.where(DispatchHistory.plate == plate)
    rows = list(db.scalars(q.order_by(DispatchHistory.plate, DispatchHistory.pickup_time)).all())

    # 乘客資訊(姓名/電話/時間窗)由訂單關聯
    nos = [r.source_order_no for r in rows if r.source_order_no]
    omap = {}
    if nos:
        omap = {o.source_order_no: o for o in db.scalars(
            select(Order).where(Order.source_order_no.in_(nos))).all()}

    def _task(r):
        o = omap.get(r.source_order_no)
        wc = r.wheelchair_count or 0
        welfare = wc > 0 or (bool(r.vehicle_type_req) and "小型" not in (r.vehicle_type_req or ""))
        return {
            "time": r.pickup_time.strftime("%H:%M") if r.pickup_time else "--:--",
            "passenger": (o.passenger_name if o else None),
            "phone": (o.passenger_phone if o else None),
            "pickup": r.pickup_address, "dropoff": r.dropoff_address,
            "pickup_town": r.pickup_town, "dropoff_town": r.dropoff_town,
            "pax": r.pax or 1, "wheelchair": wc, "welfare": welfare,
            "est_min": round(r.est_minutes) if r.est_minutes else None,
            "order_no": r.source_order_no,
        }

    # 分組:車行 → 車牌
    grouped: dict[str, dict[str, dict]] = {}
    for r in rows:
        veh = grouped.setdefault(r.fleet or "(未標車行)", {}).setdefault(
            r.plate, {"plate": r.plate, "driver": r.driver_name,
                      "driver_phone": r.driver_phone, "tasks": []})
        veh["tasks"].append(_task(r))

    fleets_out = []
    for fl, vehs in sorted(grouped.items()):
        vlist = []
        for pl in sorted(vehs):
            v = vehs[pl]
            v["task_count"] = len(v["tasks"])
            v["first"] = v["tasks"][0]["time"]
            v["last"] = v["tasks"][-1]["time"]
            vlist.append(v)
        fleets_out.append({"fleet": fl, "vehicles": vlist, "vehicle_count": len(vlist),
                           "task_count": sum(v["task_count"] for v in vlist)})

    return {
        "service_date": service_date.isoformat(), "fleet": fleet, "plate": plate,
        "total_vehicles": sum(f["vehicle_count"] for f in fleets_out),
        "total_tasks": len(rows),
        "fleets": fleets_out,
    }


@router.get("/traffic/etag-status")
def etag_status(db: Session = Depends(get_db)):
    """查看 TDX ETag 收集狀態：最新收集時間、總筆數、涵蓋天數。"""
    from app.models.tdx_etag_speed import TdxEtagSpeed
    total = db.scalar(select(func.count()).select_from(TdxEtagSpeed)) or 0
    latest = db.scalar(select(func.max(TdxEtagSpeed.collected_at)))
    oldest = db.scalar(select(func.min(TdxEtagSpeed.collected_at)))
    pairs = db.scalar(select(func.count(TdxEtagSpeed.etag_pair_id.distinct()))) or 0
    return {
        "total_rows": total,
        "unique_pairs": pairs,
        "latest_collected_at": latest.isoformat() if latest else None,
        "oldest_collected_at": oldest.isoformat() if oldest else None,
        "days_accumulated": (latest - oldest).days + 1 if latest and oldest else 0,
        "collector_running": bool(settings.TDX_CLIENT_ID),
    }


@router.get("/traffic/time-factors")
def time_factors():
    """查看各時段路況係數（靜態經驗值 or TDX 歷史均值）。"""
    from app.services import tdx_traffic as tdx_svc
    return {
        "source": "static",  # Phase 2 後改為 "tdx_historical"
        "factors": {
            f"{h:02d}:00": round(tdx_svc.get_time_factor(h), 3)
            for h in range(6, 21)
        },
        "note": "係數 < 1.0 表示塞車，OSRM 行程時間 ÷ 係數 = 補正後時間",
    }


@router.post("/agent-dispatch")
def agent_dispatch(
    service_date: date,
    late_tolerance_min: int = 10,
    dry_run: bool = True,
    reset_scheduled: bool = False,
    # ① 福祉車護欄
    welfare_guard: bool = True,
    welfare_guard_mul: float = 1.1,
    # ② 對數負載均衡
    log_load_balance: bool = True,
    log_lb_coeff: float = 0.05,
    # ③ 第二輪補救（分鐘；0 = 不啟用）
    second_pass_min: int = 15,
    # 每車每日趟次上限（0 = 不限）
    max_trips_welfare: int = 16,
    max_trips_normal: int = 14,
    # ④ 前瞻保護（預留，尚未實作）
    lookahead: bool = False,
    # ⑤ 共乘聚合（預留）
    shared_ride_min: int = 0,
    shared_ride_km: float = 1.0,
    db: Session = Depends(get_db),
):
    """多智能體拍賣派遣（每台車依時間序逐筆競標）。

    基本選項：
    - late_tolerance_min  遲到容忍分鐘（預設 10）
    - dry_run             true = 只模擬，不寫 DB
    - reset_scheduled     true = 清除當日所有指派，從頭全重排

    最佳化選項：
    - welfare_guard / welfare_guard_mul  ① 福祉車護欄，對 normal 訂單出價 × 倍率
    - log_load_balance / log_lb_coeff   ② 對數負載均衡，防單車包攬
    - second_pass_min                   ③ 二輪補救寬限（分鐘）；0 = 不啟用
    - lookahead                         ④ 前瞻保護（預留）
    - shared_ride_min / shared_ride_km  ⑤ 共乘聚合（預留）
    """
    return agent_dispatcher.run(
        db, service_date,
        late_tolerance_min=late_tolerance_min,
        dry_run=dry_run,
        reset_scheduled=reset_scheduled,
        welfare_guard=welfare_guard,
        welfare_guard_mul=welfare_guard_mul,
        log_load_balance=log_load_balance,
        log_lb_coeff=log_lb_coeff,
        second_pass_min=second_pass_min,
        max_trips_welfare=max_trips_welfare,
        max_trips_normal=max_trips_normal,
        lookahead=lookahead,
        shared_ride_min=shared_ride_min,
        shared_ride_km=shared_ride_km,
    )
