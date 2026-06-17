"""常客固定駕駛(軟性偏好):從歷史派遣萃取『乘客 → 慣用駕駛』。

資料實況:全域訊號偏弱(688 位常客中,最常司機占比中位僅 ~27%,僅 ~7% ≥50%),
故僅作**高信心建議**(集中度達門檻才推薦),供人工指派參考;不接進批次硬排。
類比 zone_affinity 的保守用法。純讀,不寫資料。
"""
from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dispatch_history import DispatchHistory
from app.models.order import Order


def _passenger_driver_counts(db: Session, passenger: str | None = None):
    q = (
        select(Order.passenger_name, DispatchHistory.driver_name)
        .join(DispatchHistory, DispatchHistory.source_order_no == Order.source_order_no)
        .where(
            Order.passenger_name.is_not(None),
            DispatchHistory.driver_name.is_not(None),
            Order.status == "done",
        )
    )
    if passenger:
        q = q.where(Order.passenger_name == passenger)
    pd: dict[str, Counter] = defaultdict(Counter)
    for pax, drv in db.execute(q).all():
        pd[pax][drv] += 1
    return pd


def suggest(db: Session, passenger: str, min_trips: int = 5,
            min_ratio: float = 0.5, top_n: int = 3) -> dict:
    """單一乘客的慣用駕駛排行 + 是否達高信心(可作軟性偏好)。"""
    pd = _passenger_driver_counts(db, passenger)
    counter = pd.get(passenger)
    if not counter:
        return {"passenger": passenger, "trips": 0, "confident": False, "drivers": []}
    total = sum(counter.values())
    drivers = [
        {"driver": d, "trips": n, "ratio": round(n / total, 2)}
        for d, n in counter.most_common(top_n)
    ]
    top = drivers[0]
    confident = total >= min_trips and top["ratio"] >= min_ratio
    return {
        "passenger": passenger, "trips": total,
        "confident": confident,
        "preferred_driver": top["driver"] if confident else None,
        "drivers": drivers,
    }


def loyal_passengers(db: Session, min_trips: int = 5,
                     min_ratio: float = 0.5, limit: int = 100) -> dict:
    """高忠誠乘客清單:集中度達門檻者,適合排班時優先沿用慣用駕駛(軟性偏好)。"""
    pd = _passenger_driver_counts(db)
    out = []
    for pax, counter in pd.items():
        total = sum(counter.values())
        if total < min_trips:
            continue
        drv, n = counter.most_common(1)[0]
        ratio = n / total
        if ratio >= min_ratio:
            out.append({
                "passenger": pax, "preferred_driver": drv,
                "trips": total, "with_driver": n, "ratio": round(ratio, 2),
            })
    out.sort(key=lambda x: (x["ratio"], x["trips"]), reverse=True)
    return {
        "min_trips": min_trips, "min_ratio": min_ratio,
        "eligible_passengers": sum(1 for c in pd.values() if sum(c.values()) >= min_trips),
        "loyal_count": len(out),
        "passengers": out[:limit],
    }
