"""營運報表彙總(需登入)。"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.driver import Driver
from app.models.order import Order
from app.models.vehicle import Vehicle

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user)])


@router.get("/overview")
def overview(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """區間營運彙總:狀態/車種分佈、每日量、派遣率、車輛使用。預設近 14 天。"""
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=13)

    base = select(Order).where(
        Order.service_date >= date_from, Order.service_date <= date_to
    ).subquery()
    o = Order

    def in_range(stmt):
        return stmt.where(o.service_date >= date_from, o.service_date <= date_to)

    total = db.scalar(in_range(select(func.count()).select_from(o))) or 0

    by_status = dict(
        db.execute(in_range(select(o.status, func.count()).group_by(o.status))).all()
    )
    by_vehicle_type = dict(
        db.execute(in_range(select(o.vehicle_type, func.count()).group_by(o.vehicle_type))).all()
    )

    # 每日:總數 / 已派 / 未派(未派 = 非 scheduled/ongoing/done/canceled,即仍 imported)
    rows = db.execute(
        in_range(
            select(
                o.service_date,
                func.count(),
                func.count().filter(o.assigned_vehicle_id.is_not(None)),
            ).group_by(o.service_date).order_by(o.service_date)
        )
    ).all()
    by_day = [
        {"date": d.isoformat(), "total": t, "assigned": a, "unassigned": t - a}
        for (d, t, a) in rows
    ]

    # 每車派遣量(區間內)
    veh_rows = db.execute(
        in_range(
            select(o.assigned_vehicle_id, func.count())
            .where(o.assigned_vehicle_id.is_not(None))
            .group_by(o.assigned_vehicle_id)
        )
    ).all()
    vehicle_names = dict(db.execute(select(Vehicle.id, Vehicle.plate)).all())
    per_vehicle = [
        {"vehicle_id": vid, "plate": vehicle_names.get(vid) or f"車#{vid}", "orders": cnt}
        for (vid, cnt) in veh_rows
    ]

    assigned = sum(v["orders"] for v in per_vehicle)

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "totals": {
            "orders": total,
            "assigned": assigned,
            "unassigned": total - assigned,
            "vehicles_active": db.scalar(select(func.count()).select_from(Vehicle).where(Vehicle.active.is_(True))) or 0,
            "vehicles_total": db.scalar(select(func.count()).select_from(Vehicle)) or 0,
            "drivers": db.scalar(select(func.count()).select_from(Driver)) or 0,
        },
        "by_status": by_status,
        "by_vehicle_type": by_vehicle_type,
        "by_day": by_day,
        "per_vehicle": per_vehicle,
    }
