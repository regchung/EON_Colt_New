"""司機↔車輛對應解析(地基)。

目的:給定司機姓名(與日期),回傳其當日駕駛的車輛。供休假/調班、固定行程、口卡等
以「司機」為操作對象的功能共用,取代各處不可靠的「首見」對應。

優先序(主題1A 先做 a/c;1B 補當日指派):
  a) 當日駕駛-車輛指派(driver_vehicle_assignment)— 1B 加入
  b) Driver.vehicle_id 預設車
  c) 查無 → None
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.fixed_route import FixedRoute
from app.models.vehicle import Vehicle


def resolve(db: Session, driver_name: str, service_date: date | None = None) -> Vehicle | None:
    """回傳該司機(當日)駕駛的車輛;查無回 None。"""
    if not driver_name:
        return None
    d = db.scalar(select(Driver).where(Driver.name == driver_name.strip()))
    if d is None:
        return None
    # 1B 將在此優先查 driver_vehicle_assignment(service_date)
    if d.vehicle_id:
        return db.get(Vehicle, d.vehicle_id)
    return None


def status_list(db: Session, fleet: str | None = None, missing_only: bool = False) -> list[dict]:
    """所有司機 + 對應車輛 + 是否無車(供「司機車輛」管理頁)。"""
    q = select(Driver).order_by(Driver.home_fleet, Driver.name)
    if fleet:
        q = q.where(Driver.home_fleet == fleet)
    drivers = list(db.scalars(q).all())
    vmap = {v.id: v for v in db.scalars(select(Vehicle)).all()}
    out = []
    for d in drivers:
        v = vmap.get(d.vehicle_id) if d.vehicle_id else None
        if missing_only and v is not None:
            continue
        out.append({
            "driver_id": d.id, "name": d.name, "phone": d.phone,
            "home_fleet": d.home_fleet, "active": d.active,
            "vehicle_id": d.vehicle_id, "plate": v.plate if v else None,
            "vehicle_type": v.type if v else None, "seats": v.seats if v else None,
            "has_vehicle": v is not None,
        })
    return out


def fixed_route_unresolved(db: Session) -> list[str]:
    """啟用中的固定行程裡,無法對應到車輛的司機姓名(未建檔或無車)。"""
    names = {r.driver_name for r in db.scalars(
        select(FixedRoute).where(FixedRoute.active.is_(True))).all() if r.driver_name}
    return sorted(n for n in names if resolve(db, n) is None)
