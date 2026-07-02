from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crud.vehicle import vehicle as crud
from app.db.session import get_db
from app.schemas.vehicle import VehicleCreate, VehicleOut, VehicleUpdate

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=list[VehicleOut])
def list_vehicles(
    skip: int = 0,
    limit: int = 100,
    type: str | None = None,
    active: bool | None = None,
    db: Session = Depends(get_db),
):
    return crud.list(db, skip=skip, limit=limit, type=type, active=active)


@router.post("", response_model=VehicleOut, status_code=201)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db)):
    return crud.create(db, payload)


@router.get("/{id}", response_model=VehicleOut)
def get_vehicle(id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return obj


@router.put("/{id}", response_model=VehicleOut)
def update_vehicle(id: int, payload: VehicleUpdate, db: Session = Depends(get_db)):
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    # PATCH 語意:只更新請求有送的欄位,避免部分 payload 把 start/end/depot 等座標清空。
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/{id}/suspend", response_model=VehicleOut)
def set_vehicle_suspended(id: int, value: bool = True, db: Session = Depends(get_db)):
    """切換車輛停派狀態(value=true 停派 / false 啟用)。停派車不納入自動派遣。"""
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    obj.suspended = value
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{id}", status_code=204)
def delete_vehicle(id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    crud.delete(db, obj)
