"""司機 App 端點：路單查看 + 狀態回報。"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_dispatcher
from app.db.session import get_db
from app.models.order import Order
from app.models.route import RouteStop
from app.models.user import User

router = APIRouter(prefix="/driver", tags=["driver"])


class StopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    seq: int
    kind: str
    order_id: int | None
    address: str | None
    eta: str | None
    lng: float | None
    lat: float | None

    @classmethod
    def from_stop(cls, s: RouteStop) -> "StopOut":
        return cls(
            id=s.id, seq=s.seq, kind=s.kind, order_id=s.order_id,
            address=s.address,
            eta=s.eta.strftime("%H:%M") if s.eta else None,
            lng=s.lng, lat=s.lat,
        )


class OrderStatusOut(BaseModel):
    order_id: int
    status: str


@router.get("/my-route")
def my_route(
    service_date: date | None = None,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """司機查看自己當日路單（依 token 對應 vehicle_id）。"""
    if current.role == "driver":
        if not current.vehicle_id:
            raise HTTPException(status_code=400, detail="此帳號尚未綁定車輛，請聯繫管理員")
        vid = current.vehicle_id
    elif current.role in ("admin", "dispatcher"):
        raise HTTPException(status_code=400, detail="請使用 /dispatch/routes-geojson 查看所有路線")
    else:
        raise HTTPException(status_code=403, detail="無權限")

    target_date = service_date or date.today()
    stops = list(
        db.scalars(
            select(RouteStop)
            .where(RouteStop.service_date == target_date, RouteStop.vehicle_id == vid)
            .order_by(RouteStop.seq)
        ).all()
    )
    orders_on_route = {}
    if stops:
        order_ids = [s.order_id for s in stops if s.order_id]
        if order_ids:
            rows = db.scalars(select(Order).where(Order.id.in_(order_ids))).all()
            orders_on_route = {o.id: o.status for o in rows}

    return {
        "vehicle_id": vid,
        "service_date": target_date.isoformat(),
        "stops": [StopOut.from_stop(s) for s in stops],
        "order_statuses": orders_on_route,
    }


_VALID_TRANSITIONS = {
    "scheduled": ["ongoing"],
    "ongoing": ["done"],
}

ALLOWED_STATUS = {"ongoing", "done"}


@router.post("/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    value: str,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """司機回報訂單狀態（scheduled→ongoing→done）。"""
    if value not in ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail=f"不允許的狀態值：{value}")

    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="訂單不存在")

    # 司機只能更新自己車輛的訂單
    if current.role == "driver":
        if not current.vehicle_id or order.assigned_vehicle_id != current.vehicle_id:
            raise HTTPException(status_code=403, detail="此訂單不屬於您的車輛")

    allowed = _VALID_TRANSITIONS.get(order.status, [])
    if value not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"訂單目前狀態 {order.status}，不可轉為 {value}",
        )

    order.status = value
    db.commit()
    return {"order_id": order_id, "status": order.status}


@router.get("/vehicles", dependencies=[Depends(require_dispatcher)])
def list_vehicles_for_binding(db: Session = Depends(get_db)):
    """派遣員/管理員查詢可綁定的車輛列表（供建立司機帳號時選用）。"""
    from app.models.vehicle import Vehicle
    vehicles = db.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.id)).all()
    return [{"id": v.id, "plate": v.plate, "type": v.type} for v in vehicles]
