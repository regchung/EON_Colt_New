"""派遣相關端點(本階段:距離矩陣引擎驗證;下一步:VROOM 排班)。"""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.dispatch_comparison import DispatchComparison
from app.models.order import Order
from app.models.pool_projection import PoolProjection
from app.models.route import RouteStop
from app.models.user import User
from app.services import (
    ai_dispatch, comparison, dispatcher, driver_affinity, forecast, matrix, osrm,
    pool_suggest, recurring_pairs, zone_affinity,
)
from app.services import settings as app_settings

router = APIRouter(prefix="/dispatch", tags=["dispatch"])

# 每車一個顏色(地圖用)
_COLORS = ["#e6194B", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6", "#bfef45"]


@router.post("/run")
def run(service_date: date, ai: bool = False, db: Session = Depends(get_db)):
    """對某日訂單執行 VROOM 自動排班，寫回派遣結果並回傳路線報告。
    ai=true 時額外呼叫 Claude 產出 AI 分析摘要。
    """
    result = dispatcher.run_dispatch(db, service_date)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    if ai:
        result["ai_summary"] = ai_dispatch.analyze_dispatch(result)
    return result


@router.post("/zone-suggest")
def zone_suggest(order_id: int, service_date: date, db: Session = Depends(get_db)):
    """區域親和建議:同區新單優先推薦給今天已在該區的司機(dry-run,不寫入)。

    硬條件(車種/輪椅、座位)在排名前過濾;時間窗精確可行性由實際排班確認。
    """
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="訂單不存在")
    return zone_affinity.suggest(db, order, service_date)


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
def comparison_list(fleet: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    """逐日對比明細。"""
    q = select(DispatchComparison).order_by(
        DispatchComparison.saved_vehicles.desc(), DispatchComparison.service_date
    )
    if fleet:
        q = q.where(DispatchComparison.fleet == fleet)
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
