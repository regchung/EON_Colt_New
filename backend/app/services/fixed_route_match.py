"""固定行程匹配:把某日訂單對應到固定行程規則與指定司機/車輛。

匹配:規則 keyword 出現在訂單的 case_tag/上下車地址(依 match_field),且符合時段(早/午/午後/早晚/全天)。
指定車輛由 driver_resolve.resolve(司機, 日期) 解出(當日輪車 > 預設車)。
供「預覽比對」與「派遣整合(以 skills 釘車)」共用。
"""
from __future__ import annotations

from datetime import date, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fixed_route import FixedRoute
from app.models.order import Order
from app.services import driver_resolve

TW = timezone(timedelta(hours=8))


def _hour(o: Order) -> int | None:
    if not o.pickup_time:
        return None
    return (o.pickup_time.astimezone(TW) if o.pickup_time.tzinfo else o.pickup_time).hour


def _slot_ok(slot: str, hour: int | None) -> bool:
    if slot in (None, "", "全天") or hour is None:
        return True
    if slot == "早":
        return hour < 12
    if slot == "午":
        return 11 <= hour < 14
    if slot == "午後":
        return hour >= 12
    if slot == "早晚":
        return hour < 10 or hour >= 16
    return True


def _haystack(o: Order) -> str:
    return " ".join(filter(None, [o.case_tag, o.pickup_address, o.dropoff_address, o.passenger_name]))


def match_for_date(db: Session, service_date: date) -> dict:
    """回傳某日固定行程比對結果。

    {
      "pins": {order_id: vehicle_id},        # 可派(司機解出車輛)的釘選
      "items": [ {order_id, label, driver_name, plate, vehicle_id, on_resolvable, time, ...} ],
      "unresolved_rules": [ {label, driver_name} ],  # 有匹配但司機無車
    }
    """
    rules = list(db.scalars(select(FixedRoute).where(FixedRoute.active.is_(True))).all())
    orders = list(db.scalars(select(Order).where(Order.service_date == service_date)).all())
    pins: dict[int, int] = {}
    items: list[dict] = []
    unresolved: dict[str, str] = {}

    for o in orders:
        hay = _haystack(o)
        if not hay:
            continue
        h = _hour(o)
        for r in rules:
            if r.keyword and r.keyword in hay and _slot_ok(r.time_slot, h):
                veh = driver_resolve.resolve(db, r.driver_name, service_date)
                rec = {
                    "order_id": o.id, "rule_id": r.id, "label": r.label,
                    "driver_name": r.driver_name, "time_slot": r.time_slot,
                    "keyword": r.keyword,
                    "time": o.pickup_time.astimezone(TW).strftime("%H:%M") if o.pickup_time else None,
                    "passenger": o.passenger_name,
                    "pickup": o.pickup_address, "dropoff": o.dropoff_address,
                    "plate": veh.plate if veh else None,
                    "vehicle_id": veh.id if veh else None,
                    "resolvable": veh is not None,
                }
                items.append(rec)
                if veh is not None:
                    pins[o.id] = veh.id
                else:
                    unresolved[r.driver_name] = r.label
                break  # 一單對到第一條規則即止

    items.sort(key=lambda x: (x["label"], x["time"] or ""))
    return {
        "service_date": service_date.isoformat(),
        "matched": len(items),
        "pinnable": len(pins),
        "pins": pins,
        "items": items,
        "unresolved_rules": [{"driver_name": k, "label": v} for k, v in sorted(unresolved.items())],
    }
