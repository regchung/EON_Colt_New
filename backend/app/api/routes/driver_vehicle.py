"""司機↔車輛 管理(地基):檢視對應、為司機指派既有車或建新車、當日輪車指派。需派遣員以上。"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_dispatcher
from app.db.session import get_db
from app.models.driver import Driver
from app.models.driver_vehicle_assignment import DriverVehicleAssignment
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import driver_resolve

router = APIRouter(prefix="/driver-vehicle", tags=["driver-vehicle"])


@router.get("")
def list_status(fleet: str | None = None, missing_only: bool = False,
                db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    """所有司機 + 對應車 + 是否無車。"""
    rows = driver_resolve.status_list(db, fleet, missing_only)
    return {"count": len(rows), "missing": sum(1 for r in rows if not r["has_vehicle"]),
            "fixed_route_unresolved": driver_resolve.fixed_route_unresolved(db),
            "drivers": rows}


class CreateDriverIn(BaseModel):
    name: str
    home_fleet: str | None = None
    phone: str | None = None
    plate: str | None = None         # 一併建/連結車輛(選填)
    seats: int = 4
    type: str = "normal"


@router.post("/create-driver")
def create_driver(body: CreateDriverIn, db: Session = Depends(get_db),
                  _: User = Depends(require_dispatcher)):
    """新增司機(可一併建立/連結車輛);用於補齊固定行程引用但未建檔的司機。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="姓名必填")
    d = db.scalar(select(Driver).where(Driver.name == name))
    if d is None:
        d = Driver(name=name, home_fleet=body.home_fleet, phone=body.phone, active=True)
        db.add(d)
        db.flush()
    vehicle_created = False
    if body.plate and body.plate.strip():
        plate = body.plate.strip()
        v = db.scalar(select(Vehicle).where(Vehicle.plate == plate))
        if v is None:
            v = Vehicle(plate=plate, type=body.type, seats=max(1, body.seats),
                        active=True, home_fleet=body.home_fleet or d.home_fleet)
            db.add(v)
            db.flush()
            vehicle_created = True
        d.vehicle_id = v.id
    db.commit()
    return {"driver_id": d.id, "name": d.name, "vehicle_id": d.vehicle_id,
            "vehicle_created": vehicle_created}


class AssignIn(BaseModel):
    plate: str                       # 車牌(既有則連結,不存在則建立)
    seats: int = 4
    type: str = "normal"             # welfare | normal
    fleet: str | None = None


@router.post("/{driver_id}/assign")
def assign_vehicle(driver_id: int, body: AssignIn,
                   db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    """為司機指派車輛:車牌既有→連結;不存在→建立新車後連結。"""
    d = db.get(Driver, driver_id)
    if d is None:
        raise HTTPException(status_code=404, detail="司機不存在")
    plate = body.plate.strip()
    if not plate:
        raise HTTPException(status_code=400, detail="車牌必填")
    v = db.scalar(select(Vehicle).where(Vehicle.plate == plate))
    created = False
    if v is None:
        v = Vehicle(plate=plate, type=body.type, seats=max(1, body.seats),
                    active=True, home_fleet=body.fleet or d.home_fleet)
        db.add(v)
        db.flush()
        created = True
    d.vehicle_id = v.id
    db.commit()
    return {"driver_id": d.id, "name": d.name, "plate": v.plate,
            "vehicle_id": v.id, "vehicle_created": created}


@router.delete("/{driver_id}/assign")
def unassign_vehicle(driver_id: int, db: Session = Depends(get_db),
                     _: User = Depends(require_dispatcher)):
    """解除司機與車輛的對應(不刪車)。"""
    d = db.get(Driver, driver_id)
    if d is None:
        raise HTTPException(status_code=404, detail="司機不存在")
    d.vehicle_id = None
    db.commit()
    return {"driver_id": d.id, "vehicle_id": None}


# ---- 當日輪車指派(主題1B)----
@router.get("/daily")
def list_daily(service_date: date, db: Session = Depends(get_db),
               _: User = Depends(require_dispatcher)):
    """某日的駕駛-車輛指派(輪車覆寫);未指派者沿用預設車。"""
    rows = list(db.scalars(select(DriverVehicleAssignment).where(
        DriverVehicleAssignment.service_date == service_date)).all())
    dmap = {d.id: d for d in db.scalars(select(Driver)).all()}
    vmap = {v.id: v for v in db.scalars(select(Vehicle)).all()}
    return {"service_date": service_date.isoformat(), "count": len(rows), "items": [
        {"id": a.id, "driver_id": a.driver_id,
         "driver_name": dmap[a.driver_id].name if a.driver_id in dmap else None,
         "vehicle_id": a.vehicle_id, "plate": vmap[a.vehicle_id].plate if a.vehicle_id in vmap else None,
         "note": a.note}
        for a in rows]}


class DailyAssignIn(BaseModel):
    service_date: date
    driver_id: int
    plate: str
    note: str | None = None


@router.post("/daily")
def upsert_daily(body: DailyAssignIn, db: Session = Depends(get_db),
                 _: User = Depends(require_dispatcher)):
    """設定某日某司機開哪台(以既有車牌);同(日,司機)覆寫。"""
    d = db.get(Driver, body.driver_id)
    if d is None:
        raise HTTPException(status_code=404, detail="司機不存在")
    v = db.scalar(select(Vehicle).where(Vehicle.plate == body.plate.strip()))
    if v is None:
        raise HTTPException(status_code=404, detail="車牌不存在,請先於「司機車輛」建立")
    a = db.scalar(select(DriverVehicleAssignment).where(
        DriverVehicleAssignment.service_date == body.service_date,
        DriverVehicleAssignment.driver_id == body.driver_id))
    if a is None:
        a = DriverVehicleAssignment(service_date=body.service_date, driver_id=body.driver_id)
        db.add(a)
    a.vehicle_id = v.id
    a.note = body.note
    db.commit()
    return {"id": a.id, "driver_id": a.driver_id, "plate": v.plate,
            "service_date": body.service_date.isoformat()}


@router.delete("/daily/{assign_id}")
def delete_daily(assign_id: int, db: Session = Depends(get_db),
                 _: User = Depends(require_dispatcher)):
    a = db.get(DriverVehicleAssignment, assign_id)
    if a is None:
        raise HTTPException(status_code=404, detail="指派不存在")
    db.delete(a)
    db.commit()
    return {"deleted": assign_id}
