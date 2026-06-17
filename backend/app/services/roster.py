"""班表服務:解析某日出勤車輛 + 從歷史回推週期班表。

可用性優先序:當日例外 > 週期班表 > 無資料(保守視為不可用)。
回傳每車的班別時段(秒;None 表示用服務時段預設)。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, time

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.models.dispatch_history import DispatchHistory
from app.models.shift import ShiftException, ShiftPattern
from app.models.vehicle import Vehicle


def _secs(t: time | None):
    return t.hour * 3600 + t.minute * 60 + t.second if t else None


def available_vehicles(db: Session, service_date: date) -> dict[int, tuple[int | None, int | None]]:
    """回傳 {vehicle_id: (start_sec|None, end_sec|None)},僅含當日出勤車輛。"""
    wd = service_date.weekday()  # 0=Mon … 6=Sun
    active_ids = set(db.scalars(select(Vehicle.id).where(Vehicle.active.is_(True))).all())

    exc = {
        e.vehicle_id: e
        for e in db.scalars(select(ShiftException).where(ShiftException.ex_date == service_date)).all()
    }
    pat = {
        p.vehicle_id: p
        for p in db.scalars(select(ShiftPattern).where(ShiftPattern.weekday == wd)).all()
    }

    out: dict[int, tuple[int | None, int | None]] = {}
    for vid in active_ids:
        if vid in exc:                         # 1) 當日例外優先
            e = exc[vid]
            if e.available:
                out[vid] = (_secs(e.shift_start), _secs(e.shift_end))
            # available=False → 不出勤,略過
        elif vid in pat:                       # 2) 週期班表
            p = pat[vid]
            out[vid] = (_secs(p.shift_start), _secs(p.shift_end))
        # 3) 無資料 → 保守視為不可用(不納入)
    return out


def has_any_roster(db: Session) -> bool:
    return bool(db.scalar(select(ShiftPattern.id).limit(1)) or
                db.scalar(select(ShiftException.id).limit(1)))


def seed_from_history(db: Session, min_times: int = 3) -> dict:
    """從 dispatch_history 回推每車週期班表:某 weekday 出勤達 min_times 次 → 設為常態上班日。

    冪等:先清空既有 ShiftPattern 再重建(不動 ShiftException)。
    """
    plate_to_id = {
        v.plate: v.id
        for v in db.scalars(select(Vehicle).where(Vehicle.plate.is_not(None))).all()
    }
    # (vehicle_id, weekday) -> 出勤的不同日期數
    seen: dict[tuple[int, int], set] = defaultdict(set)
    rows = db.execute(
        select(distinct(DispatchHistory.plate), DispatchHistory.service_date)
        .where(DispatchHistory.status == "已轉至正式單", DispatchHistory.plate.like("R%"))
    ).all()
    for plate, sd in rows:
        vid = plate_to_id.get(plate)
        if vid and sd:
            seen[(vid, sd.weekday())].add(sd)

    db.query(ShiftPattern).delete()
    created = 0
    vehicles_covered = set()
    for (vid, wd), dates in seen.items():
        if len(dates) >= min_times:
            db.add(ShiftPattern(vehicle_id=vid, weekday=wd))
            created += 1
            vehicles_covered.add(vid)
    db.commit()
    return {"patterns_created": created, "vehicles_covered": len(vehicles_covered),
            "min_times": min_times}
