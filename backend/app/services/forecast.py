"""輕量需求預測(weekday 季節基線)。

刻意不引入重量級模型(TimesFM 等):本專案為預約制、資料約 1 年內、主訊號為週循環,
以「近 N 週同 weekday 平均」即可給出可用的『各日趟次/建議排車數』,零額外基礎設施。
資料夠長且需細粒度多序列時,再評估基礎模型(見 CLAUDE.md)。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models.dispatch_history import DispatchHistory
from app.models.order import Order

WD_NAMES = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
SERVED = "已轉至正式單"


def _daily_counts(db: Session, fleet: str | None):
    """回傳 {date: (trips, vehicles)}(成行趟次、實際出勤車數)。"""
    tq = select(Order.service_date, func.count()).where(Order.status == "done")
    vq = select(DispatchHistory.service_date, func.count(distinct(DispatchHistory.plate))).where(
        DispatchHistory.status == SERVED, DispatchHistory.plate.like("R%"))
    if fleet:
        tq = tq.where(Order.fleet == fleet)
        vq = vq.where(DispatchHistory.fleet == fleet)
    trips = dict(db.execute(tq.group_by(Order.service_date)).all())
    vehs = dict(db.execute(vq.group_by(DispatchHistory.service_date)).all())
    out = {}
    for d in set(trips) | set(vehs):
        out[d] = (int(trips.get(d, 0)), int(vehs.get(d, 0)))
    return out


def weekday_profile(db: Session, fleet: str | None = None, lookback_weeks: int = 8) -> dict:
    """近 N 週各 weekday 的平均趟次與平均出勤車數(建議排車數)。"""
    daily = _daily_counts(db, fleet)
    if not daily:
        return {"fleet": fleet, "lookback_weeks": lookback_weeks, "weekdays": [], "last_date": None}
    last = max(daily)
    cutoff = last - timedelta(weeks=lookback_weeks)
    buckets: dict[int, list] = defaultdict(list)
    for d, (t, v) in daily.items():
        if d > cutoff:
            buckets[d.weekday()].append((t, v))
    rows = []
    for wd in range(7):
        vals = buckets.get(wd, [])
        if vals:
            avg_t = round(sum(t for t, _ in vals) / len(vals), 1)
            avg_v = round(sum(v for _, v in vals) / len(vals))
        else:
            avg_t = avg_v = 0
        rows.append({"weekday": wd, "name": WD_NAMES[wd],
                     "avg_trips": avg_t, "suggest_vehicles": avg_v, "samples": len(vals)})
    return {"fleet": fleet, "lookback_weeks": lookback_weeks,
            "last_date": last.isoformat(), "weekdays": rows}


def forecast(db: Session, fleet: str | None = None, horizon_days: int = 14,
             lookback_weeks: int = 8, start: date | None = None) -> dict:
    """未來 horizon_days 的每日趟次/建議排車預測(以 weekday 基線)。"""
    prof = weekday_profile(db, fleet, lookback_weeks)
    by_wd = {r["weekday"]: r for r in prof["weekdays"]}
    if start is None:
        last = prof.get("last_date")
        start = (date.fromisoformat(last) + timedelta(days=1)) if last else date.today()
    horizon = []
    for i in range(horizon_days):
        d = start + timedelta(days=i)
        r = by_wd.get(d.weekday(), {})
        horizon.append({
            "date": d.isoformat(), "name": WD_NAMES[d.weekday()],
            "predicted_trips": r.get("avg_trips", 0),
            "suggest_vehicles": r.get("suggest_vehicles", 0),
        })
    return {"method": "weekday-seasonal-mean", "fleet": fleet,
            "lookback_weeks": lookback_weeks, "weekday_profile": prof["weekdays"],
            "horizon": horizon}
