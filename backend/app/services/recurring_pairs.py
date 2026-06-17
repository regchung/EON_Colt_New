"""常態共乘對挖掘:找出『反覆在相近時間、相近起訖點』同行的乘客對。

用途:這類乘客對(如同安養院兩位每週同院洗腎)最值得一次徵得**長期共乘同意**,
徵一次即可覆蓋未來多日,比每日逐筆徵詢有效率。純讀歷史,不寫資料。

判定某日「可同乘」:同車行同日、上車時間差 ≤ time_tol、上車點與下車點皆相近(haversine)。
累計每組(乘客A,乘客B)可同乘的天數,取 ≥ min_days 者為常態共乘對。
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order


def _haversine_m(lng1, lat1, lng2, lat2) -> float:
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * asin(sqrt(a))


def find(db: Session, min_days: int = 3, time_tol_min: int = 30,
         near_m: float = 1500.0, limit: int = 100) -> dict:
    rows = list(db.scalars(
        select(Order).where(
            Order.status == "done",
            Order.passenger_name.is_not(None),
            Order.pickup_lng.is_not(None), Order.dropoff_lng.is_not(None),
        )
    ).all())

    # 依 (車行, 日) 分組
    by_day: dict[tuple, list[Order]] = {}
    for o in rows:
        by_day.setdefault((o.fleet, o.service_date), []).append(o)

    tol = time_tol_min * 60
    pairs: dict[tuple[str, str], dict] = {}

    for (fleet, _sd), os in by_day.items():
        n = len(os)
        for i in range(n):
            a = os[i]
            for j in range(i + 1, n):
                b = os[j]
                if a.passenger_name == b.passenger_name:
                    continue
                # 時間相近
                if abs((a.pickup_time - b.pickup_time).total_seconds()) > tol:
                    continue
                # 起點與終點皆相近
                if _haversine_m(a.pickup_lng, a.pickup_lat, b.pickup_lng, b.pickup_lat) > near_m:
                    continue
                if _haversine_m(a.dropoff_lng, a.dropoff_lat, b.dropoff_lng, b.dropoff_lat) > near_m:
                    continue
                key = tuple(sorted([a.passenger_name, b.passenger_name]))
                rec = pairs.setdefault(key, {
                    "passengers": list(key), "fleet": fleet, "days": 0,
                    "both_consented_days": 0,
                    "sample_pickup": a.pickup_address, "sample_dropoff": a.dropoff_address,
                })
                rec["days"] += 1
                if a.allow_pool and b.allow_pool:
                    rec["both_consented_days"] += 1

    result = [p for p in pairs.values() if p["days"] >= min_days]
    result.sort(key=lambda p: p["days"], reverse=True)
    return {
        "min_days": min_days, "time_tol_min": time_tol_min, "near_m": near_m,
        "pairs_found": len(result),
        "pairs": result[:limit],
    }
