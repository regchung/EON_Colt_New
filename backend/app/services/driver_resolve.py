"""司機↔車輛對應解析。

給定司機姓名與服務日期，從當日出勤名冊(ShiftException.driver_id)查出該司機駕駛的車輛。
無日期時查無法回傳車輛(不再有靜態預設車對應)。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.fixed_route import FixedRoute
from app.models.shift import ShiftException
from app.models.vehicle import Vehicle


def resolve(db: Session, driver_name: str, service_date: date | None = None) -> Vehicle | None:
    """回傳該司機在 service_date 當日駕駛的車輛；查無或無日期回 None。"""
    if not driver_name or service_date is None:
        return None
    d = db.scalar(select(Driver).where(Driver.name == driver_name.strip()))
    if d is None:
        return None
    exc = db.scalar(select(ShiftException).where(
        ShiftException.driver_id == d.id,
        ShiftException.ex_date == service_date,
        ShiftException.available.is_(True),
    ))
    if exc:
        return db.get(Vehicle, exc.vehicle_id)
    return None


def status_list(db: Session, fleet: str | None = None,
                service_date: date | None = None) -> list[dict]:
    """所有司機清單；若提供 service_date，附帶當日出勤車輛資訊。"""
    q = select(Driver).order_by(Driver.home_fleet, Driver.name)
    if fleet:
        q = q.where(Driver.home_fleet == fleet)
    drivers = list(db.scalars(q).all())

    # 當日出勤：driver_id → vehicle_id
    dvmap: dict[int, int] = {}
    if service_date:
        for exc in db.scalars(select(ShiftException).where(
            ShiftException.ex_date == service_date,
            ShiftException.available.is_(True),
            ShiftException.driver_id.is_not(None),
        )).all():
            dvmap[exc.driver_id] = exc.vehicle_id

    vmap = {v.id: v for v in db.scalars(select(Vehicle)).all()}
    out = []
    for d in drivers:
        vid = dvmap.get(d.id)
        v = vmap.get(vid) if vid else None
        out.append({
            "driver_id": d.id, "name": d.name, "phone": d.phone,
            "home_fleet": d.home_fleet, "active": d.active,
            "vehicle_id": vid, "plate": v.plate if v else None,
            "vehicle_type": v.type if v else None, "seats": v.seats if v else None,
            "has_vehicle": v is not None,
        })
    return out


def fixed_route_unresolved(db: Session, service_date: date | None = None) -> list[str]:
    """啟用中的固定行程裡，指定日期查無出勤車輛的司機姓名。"""
    names = {r.driver_name for r in db.scalars(
        select(FixedRoute).where(FixedRoute.active.is_(True))).all() if r.driver_name}
    return sorted(n for n in names if resolve(db, n, service_date) is None)
