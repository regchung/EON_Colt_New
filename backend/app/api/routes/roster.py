"""班表 API:週期班表 + 例外 + 當日出勤查詢 + 從歷史回推(需派遣員/管理者)。"""
from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_dispatcher
from app.db.session import get_db
from app.models.shift import ShiftException, ShiftPattern
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import attendance_parse
from app.services import roster as roster_svc

router = APIRouter(prefix="/roster", tags=["roster"])


@router.get("/availability")
def availability(service_date: date, db: Session = Depends(get_db)):
    """某日出勤車輛清單(供確認/即時派遣)。"""
    duty = roster_svc.available_vehicles(db, service_date)
    plates = {v.id: v.plate for v in db.scalars(select(Vehicle)).all()}
    return {
        "service_date": service_date.isoformat(),
        "count": len(duty),
        "vehicles": [
            {"vehicle_id": vid, "plate": plates.get(vid),
             "shift_start": s, "shift_end": e}
            for vid, (s, e) in sorted(duty.items())
        ],
    }


@router.get("/patterns")
def list_patterns(db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    """每車的常態上班日(weekday 清單)+ 班別時段(起/迄),供班表頁顯示與編輯。

    時段採每車單一值(套用所有上班日);取任一上班日的非空時段呈現。
    """
    rows = db.scalars(select(ShiftPattern)).all()
    by_veh: dict[int, list[int]] = {}
    shift_by_veh: dict[int, tuple] = {}
    for p in rows:
        by_veh.setdefault(p.vehicle_id, []).append(p.weekday)
        if p.vehicle_id not in shift_by_veh and (p.shift_start or p.shift_end):
            shift_by_veh[p.vehicle_id] = (p.shift_start, p.shift_end)
    vehicles = db.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.id)).all()
    out = []
    for v in vehicles:
        ss, se = shift_by_veh.get(v.id, (None, None))
        out.append({
            "vehicle_id": v.id, "plate": v.plate, "home_fleet": v.home_fleet,
            "weekdays": sorted(by_veh.get(v.id, [])),
            "shift_start": ss.strftime("%H:%M") if ss else None,
            "shift_end": se.strftime("%H:%M") if se else None,
        })
    return out


class PatternIn(BaseModel):
    weekdays: list[int]                 # 0=Mon … 6=Sun
    shift_start: time | None = None
    shift_end: time | None = None


@router.put("/patterns/{vehicle_id}")
def set_pattern(vehicle_id: int, body: PatternIn,
                db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    """設定某車的常態上班日(整批覆寫)。"""
    if not db.get(Vehicle, vehicle_id):
        raise HTTPException(status_code=404, detail="車輛不存在")
    db.query(ShiftPattern).filter(ShiftPattern.vehicle_id == vehicle_id).delete()
    for wd in sorted(set(body.weekdays)):
        if 0 <= wd <= 6:
            db.add(ShiftPattern(vehicle_id=vehicle_id, weekday=wd,
                                shift_start=body.shift_start, shift_end=body.shift_end))
    db.commit()
    return {"vehicle_id": vehicle_id, "weekdays": sorted(set(body.weekdays))}


@router.get("/exceptions")
def list_exceptions(date_from: date | None = None, date_to: date | None = None,
                    db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    q = select(ShiftException).order_by(ShiftException.ex_date.desc())
    if date_from:
        q = q.where(ShiftException.ex_date >= date_from)
    if date_to:
        q = q.where(ShiftException.ex_date <= date_to)
    plates = {v.id: v.plate for v in db.scalars(select(Vehicle)).all()}
    return [
        {"id": e.id, "vehicle_id": e.vehicle_id, "plate": plates.get(e.vehicle_id),
         "ex_date": e.ex_date.isoformat(), "available": e.available, "reason": e.reason}
        for e in db.scalars(q).all()
    ]


class ExceptionIn(BaseModel):
    vehicle_id: int
    ex_date: date
    available: bool = False
    shift_start: time | None = None
    shift_end: time | None = None
    reason: str | None = None


@router.post("/exceptions")
def upsert_exception(body: ExceptionIn,
                     db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    """新增/更新單日例外(請假/維修=available False;臨時加班=True)。以(車,日)為鍵。"""
    if not db.get(Vehicle, body.vehicle_id):
        raise HTTPException(status_code=404, detail="車輛不存在")
    row = db.scalar(select(ShiftException).where(
        ShiftException.vehicle_id == body.vehicle_id, ShiftException.ex_date == body.ex_date))
    if row is None:
        row = ShiftException(vehicle_id=body.vehicle_id, ex_date=body.ex_date)
        db.add(row)
    row.available = body.available
    row.shift_start = body.shift_start
    row.shift_end = body.shift_end
    row.reason = body.reason
    db.commit()
    return {"id": row.id, "vehicle_id": row.vehicle_id, "ex_date": row.ex_date.isoformat()}


@router.delete("/exceptions/{exc_id}")
def delete_exception(exc_id: int, db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    row = db.get(ShiftException, exc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="例外不存在")
    db.delete(row)
    db.commit()
    return {"deleted": exc_id}


@router.post("/seed-from-history")
def seed_from_history(min_times: int = 3, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """從歷史派遣回推每車常態上班日(覆寫週期班表)。"""
    return roster_svc.seed_from_history(db, min_times)


@router.post("/apply-forecast")
def apply_forecast(fleet: str, lookback_weeks: int = 12, dry_run: bool = False,
                   db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    """一鍵套用需求預測的建議排車數到『該車行』週期班表。

    dry_run=true 先預覽計畫(各 weekday 建議數/實派數/缺口);false 才寫入(覆寫該車行週期班表)。
    """
    return roster_svc.apply_forecast(db, fleet, lookback_weeks, dry_run)


# ---- 自然語言出勤解析(主題2)----
class AttendanceParseIn(BaseModel):
    text: str
    service_date: date


@router.post("/parse-attendance")
def parse_attendance(body: AttendanceParseIn, db: Session = Depends(get_db),
                     _: User = Depends(require_dispatcher)):
    """貼上出勤異動文字 → Claude 解析 → 預覽(對應車輛、是否可套用)。不寫入。"""
    return attendance_parse.parse(db, body.text, body.service_date)


class AttendanceItem(BaseModel):
    vehicle_id: int
    available: bool = False
    shift_start: time | None = None
    shift_end: time | None = None
    reason: str | None = None


class AttendanceApplyIn(BaseModel):
    service_date: date
    items: list[AttendanceItem]


@router.post("/apply-attendance")
def apply_attendance(body: AttendanceApplyIn, db: Session = Depends(get_db),
                     _: User = Depends(require_dispatcher)):
    """把解析後的出勤異動寫入班表例外(以車輛+日期 upsert)。"""
    applied = 0
    for it in body.items:
        if not db.get(Vehicle, it.vehicle_id):
            continue
        row = db.scalar(select(ShiftException).where(
            ShiftException.vehicle_id == it.vehicle_id,
            ShiftException.ex_date == body.service_date))
        if row is None:
            row = ShiftException(vehicle_id=it.vehicle_id, ex_date=body.service_date)
            db.add(row)
        row.available = it.available
        row.shift_start = it.shift_start
        row.shift_end = it.shift_end
        row.reason = it.reason
        applied += 1
    db.commit()
    return {"applied": applied, "service_date": body.service_date.isoformat()}
