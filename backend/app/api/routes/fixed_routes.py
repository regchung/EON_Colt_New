"""固定行程指定司機 CRUD + 某日比對預覽(需派遣員以上)。"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_dispatcher
from app.db.session import get_db
from app.models.driver import Driver
from app.models.fixed_route import FixedRoute
from app.models.user import User
from app.schemas.fixed_route import FixedRouteCreate, FixedRouteOut, FixedRouteUpdate
from app.services import fixed_route_match

router = APIRouter(prefix="/fixed-routes", tags=["fixed-routes"])

_VALID_FIELD = {"passenger", "address", "any"}


def _driver_plate(db: Session, name: str) -> str | None:
    from app.models.vehicle import Vehicle
    d = db.scalar(select(Driver).where(Driver.name == name))
    if d and d.vehicle_id:
        v = db.get(Vehicle, d.vehicle_id)
        return v.plate if v else None
    return None


@router.get("", response_model=list[FixedRouteOut])
def list_routes(db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    return list(db.scalars(select(FixedRoute).order_by(FixedRoute.label, FixedRoute.time_slot)).all())


@router.get("/with-status")
def list_with_status(db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    """清單 + 司機是否有對應車輛(供前端標示「無車」需補)。"""
    rows = list(db.scalars(select(FixedRoute).order_by(FixedRoute.label, FixedRoute.time_slot)).all())
    out = []
    for r in rows:
        plate = _driver_plate(db, r.driver_name)
        out.append({
            "id": r.id, "label": r.label, "keyword": r.keyword, "match_name": r.match_name,
            "driver_name": r.driver_name, "time_slot": r.time_slot,
            "match_field": r.match_field, "fleet": r.fleet, "active": r.active, "note": r.note,
            "driver_plate": plate, "driver_has_vehicle": plate is not None,
        })
    return out


@router.get("/match")
def match_preview(service_date: date, db: Session = Depends(get_db),
                  _: User = Depends(require_dispatcher)):
    """比對某日訂單與固定行程規則:誰該接、司機是否有車可派。"""
    return fixed_route_match.match_for_date(db, service_date)


@router.get("/blocks")
def blocks_preview(service_date: date, db: Session = Depends(get_db),
                   _: User = Depends(require_dispatcher)):
    """固定行程既定骨架 + 衝突偵測(同司機時間重疊/銜接不及)+ 可接單空檔。"""
    from app.services import fixed_route_blocks
    return fixed_route_blocks.analyze(db, service_date)


@router.post("", response_model=FixedRouteOut, status_code=201)
def create_route(body: FixedRouteCreate, db: Session = Depends(get_db),
                 _: User = Depends(require_dispatcher)):
    if body.match_field not in _VALID_FIELD:
        raise HTTPException(status_code=400, detail="match_field 須為 passenger/address/any")
    if not (body.keyword and body.keyword.strip()) and not (body.match_name and body.match_name.strip()):
        raise HTTPException(status_code=400, detail="關鍵字與指定姓名至少需填一項")
    r = FixedRoute(**body.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.put("/{rid}", response_model=FixedRouteOut)
def update_route(rid: int, body: FixedRouteUpdate, db: Session = Depends(get_db),
                 _: User = Depends(require_dispatcher)):
    r = db.get(FixedRoute, rid)
    if r is None:
        raise HTTPException(status_code=404, detail="固定行程不存在")
    if body.match_field not in _VALID_FIELD:
        raise HTTPException(status_code=400, detail="match_field 須為 passenger/address/any")
    if not (body.keyword and body.keyword.strip()) and not (body.match_name and body.match_name.strip()):
        raise HTTPException(status_code=400, detail="關鍵字與指定姓名至少需填一項")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.commit()
    db.refresh(r)
    return r


@router.delete("/{rid}")
def delete_route(rid: int, db: Session = Depends(get_db), _: User = Depends(require_dispatcher)):
    r = db.get(FixedRoute, rid)
    if r is None:
        raise HTTPException(status_code=404, detail="固定行程不存在")
    db.delete(r)
    db.commit()
    return {"deleted": rid}
