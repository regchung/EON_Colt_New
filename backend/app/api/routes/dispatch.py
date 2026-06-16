"""派遣相關端點(本階段:距離矩陣引擎驗證;下一步:VROOM 排班)。"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.order import Order
from app.models.route import RouteStop
from app.services import ai_dispatch, dispatcher, matrix, osrm, zone_affinity

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
