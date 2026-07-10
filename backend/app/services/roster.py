"""班表服務:解析某日出勤車輛 + 從歷史回推週期班表。

可用性優先序:當日例外 > 週期班表 > 無資料(保守視為不可用)。
回傳每車的班別時段(秒;None 表示用服務時段預設)。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, time, timedelta

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.models.dispatch_history import DispatchHistory
from app.models.driver import Driver
from app.models.shift import ShiftException, ShiftPattern
from app.models.vehicle import Vehicle
from app.services import forecast as forecast_svc

SERVED = "已轉至正式單"


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


def driver_for_date(db: Session, service_date: date) -> dict[int, dict]:
    """回傳 {vehicle_id: {driver_id, name, phone}} 當日出勤名冊的司機對照。
    僅包含 ShiftException.available=True 且有 driver_id 的記錄。"""
    rows = db.execute(
        select(ShiftException.vehicle_id, ShiftException.driver_id)
        .where(ShiftException.ex_date == service_date,
               ShiftException.available.is_(True),
               ShiftException.driver_id.is_not(None))
    ).all()
    if not rows:
        return {}
    dids = {r.driver_id for r in rows}
    dmap = {d.id: d for d in db.scalars(select(Driver).where(Driver.id.in_(dids))).all()}
    return {
        r.vehicle_id: {
            "driver_id": r.driver_id,
            "name": dmap[r.driver_id].name if r.driver_id in dmap else None,
            "phone": dmap[r.driver_id].phone if r.driver_id in dmap else None,
        }
        for r in rows if r.driver_id in dmap
    }


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


def apply_forecast(db: Session, fleet: str, lookback_weeks: int = 12,
                   dry_run: bool = False) -> dict:
    """依需求預測(weekday 基線)的建議排車數,覆寫『該車行』的週期班表。

    各 weekday:取建議排車數 N,從歷史挑該日最常出勤的前 N 台(限該車行)排為常態上班。
    僅異動該車行車輛的週期班表(不影響其他車行、不動單日例外)。
    dry_run=True 只回傳計畫不寫入。
    """
    prof = forecast_svc.weekday_profile(db, fleet, lookback_weeks)
    if not prof.get("last_date"):
        return {"fleet": fleet, "applied": False, "reason": "該車行無歷史資料,無法套用"}
    suggest = {r["weekday"]: r["suggest_vehicles"] for r in prof["weekdays"]}
    last_d = date.fromisoformat(prof["last_date"])
    cutoff = last_d - timedelta(weeks=lookback_weeks)

    vehs = list(db.scalars(
        select(Vehicle).where(Vehicle.active.is_(True), Vehicle.home_fleet == fleet)
    ).all())
    if not vehs:
        return {"fleet": fleet, "applied": False, "reason": "該車行無在籍車輛(home_fleet)"}
    plate_to_id = {v.plate: v.id for v in vehs}
    fleet_vids = {v.id for v in vehs}

    # 近 lookback 期間內,各 (weekday, plate) 出勤的不同日期數 → 用於排序挑車
    rows = db.execute(
        select(distinct(DispatchHistory.plate), DispatchHistory.service_date)
        .where(DispatchHistory.fleet == fleet, DispatchHistory.status == SERVED,
               DispatchHistory.plate.like("R%"), DispatchHistory.service_date > cutoff)
    ).all()
    wd_plate: dict[int, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for plate, sd in rows:
        if sd and plate in plate_to_id:
            wd_plate[sd.weekday()][plate].add(sd)

    plan = []
    selected: dict[int, set[int]] = {}
    for wd in range(7):
        n = int(suggest.get(wd, 0) or 0)
        ranked = sorted(wd_plate.get(wd, {}).items(), key=lambda kv: len(kv[1]), reverse=True)
        chosen = ranked[:n] if n else []
        selected[wd] = {plate_to_id[p] for p, _ in chosen}
        plan.append({
            "weekday": wd, "name": forecast_svc.WD_NAMES[wd],
            "suggest": n, "assigned": len(chosen),
            "plates": [p for p, _ in chosen],
            "short": max(0, n - len(chosen)),  # 建議數 > 歷史可用車數時的缺口
        })

    if not dry_run:
        db.query(ShiftPattern).filter(
            ShiftPattern.vehicle_id.in_(fleet_vids)).delete(synchronize_session=False)
        for wd, vids in selected.items():
            for vid in vids:
                db.add(ShiftPattern(vehicle_id=vid, weekday=wd))
        db.commit()

    return {
        "fleet": fleet, "applied": not dry_run, "lookback_weeks": lookback_weeks,
        "last_date": prof["last_date"], "fleet_vehicles": len(vehs),
        "patterns_set": sum(len(s) for s in selected.values()),
        "plan": plan,
    }
