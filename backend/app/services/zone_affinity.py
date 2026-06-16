"""區域親和(Zone Affinity)派遣偏好。

規則:同一區域(以地址簿的 town/city 為界)的新單,優先指派給「今天已在該區
累積 ≥ N 筆」的司機——在不違反車種/座位等硬條件下,以加權偏好呈現建議。

定位:**建議(dry-run)**,不直接寫入。時間窗的精確可行性由實際排班(VROOM)確認。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.address import AddressAlias, AddressPoint
from app.models.order import Order
from app.models.vehicle import Vehicle


def order_zone(db: Session, o: Order) -> str | None:
    """以訂單上車地址查地址簿,回傳區域(town,退而求其次 city)。"""
    if not o.pickup_address:
        return None
    alias = db.get(AddressAlias, o.pickup_address.strip())
    if alias and alias.address_point_id:
        p = db.get(AddressPoint, alias.address_point_id)
        if p:
            return p.town or p.city
    return None


def _vehicle_feasible(v: Vehicle, o: Order) -> tuple[bool, str]:
    """硬條件:車種/輪椅、座位。時間窗留待排班確認。"""
    if (o.vehicle_type == "welfare" or o.need_wheelchair) and v.type != "welfare":
        return False, "需福祉車"
    if (v.seats or 0) < (o.pax or 1):
        return False, "座位不足"
    if not v.active:
        return False, "車輛停用"
    return True, ""


def suggest(db: Session, order: Order, service_date: date) -> dict:
    """回傳該訂單的區域親和派遣建議(排名 + 理由)。"""
    zone = order_zone(db, order)

    # 當日已派訂單(有指派車輛者)
    todays = list(db.scalars(
        select(Order)
        .where(Order.service_date == service_date)
        .where(Order.assigned_vehicle_id.is_not(None))
    ).all())

    # 計算每車:總量 + 該區量
    total_by_veh: dict[int, int] = {}
    zone_by_veh: dict[int, int] = {}
    for o in todays:
        vid = o.assigned_vehicle_id
        total_by_veh[vid] = total_by_veh.get(vid, 0) + 1
        if zone and order_zone(db, o) == zone:
            zone_by_veh[vid] = zone_by_veh.get(vid, 0) + 1

    vehicles = list(db.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.id)).all())

    suggestions = []
    for v in vehicles:
        feasible, reason = _vehicle_feasible(v, order)
        zc = zone_by_veh.get(v.id, 0)
        tc = total_by_veh.get(v.id, 0)
        over_cap = zc >= settings.ZONE_MAX_JOBS_PER_ZONE
        # 親和分數:達 N 筆者大幅加分;否則以 0 計。負載作為平衡的次要(越少越好)
        affinity = zc if zc >= settings.ZONE_MIN_JOBS_N else 0
        suggestions.append({
            "vehicle_id": v.id,
            "plate": v.plate or f"車#{v.id}",
            "type": v.type,
            "zone_count": zc,
            "total_today": tc,
            "feasible": feasible and not over_cap,
            "reason": reason or ("超過該區上限" if over_cap else ""),
            "_affinity": affinity,
        })

    # 排序:可行優先 → 親和分數高 → 該區量多 → 當日總量少(平衡)
    suggestions.sort(key=lambda s: (
        not s["feasible"], -s["_affinity"], -s["zone_count"], s["total_today"]
    ))
    for s in suggestions:
        s.pop("_affinity", None)

    feasible_list = [s for s in suggestions if s["feasible"]]
    recommended = feasible_list[0] if feasible_list else None
    triggered = bool(recommended and recommended["zone_count"] >= settings.ZONE_MIN_JOBS_N)

    return {
        "order_id": order.id,
        "zone": zone,
        "enabled": settings.ZONE_AFFINITY_ENABLED,
        "params": {
            "min_jobs_N": settings.ZONE_MIN_JOBS_N,
            "max_jobs_per_zone": settings.ZONE_MAX_JOBS_PER_ZONE,
        },
        "affinity_triggered": triggered,
        "recommended": recommended,
        "explanation": (
            f"區域「{zone}」已有司機累積 {recommended['zone_count']} 筆,優先指派 {recommended['plate']}"
            if triggered else
            ("無同區既有司機或未達門檻,建議照一般最佳化指派"
             if zone else "此訂單尚未地理編碼,無法判定區域")
        ),
        "suggestions": suggestions,
    }
