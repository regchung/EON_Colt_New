from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.crud.driver import driver as crud
from app.db.session import get_db
from app.schemas.driver import DriverCreate, DriverOut, DriverUpdate

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.get("", response_model=list[DriverOut])
def list_drivers(
    skip: int = 0,
    limit: int = 100,
    active: bool | None = None,
    db: Session = Depends(get_db),
):
    return crud.list(db, skip=skip, limit=limit, active=active)


@router.post("", response_model=DriverOut, status_code=201)
def create_driver(payload: DriverCreate, db: Session = Depends(get_db)):
    return crud.create(db, payload)


@router.get("/{id}", response_model=DriverOut)
def get_driver(id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Driver not found")
    return obj


@router.put("/{id}", response_model=DriverOut)
def update_driver(id: int, payload: DriverUpdate, db: Session = Depends(get_db)):
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Driver not found")
    return crud.update(db, obj, payload)


@router.post("/{id}/suspend", response_model=DriverOut)
def set_driver_suspended(id: int, value: bool = True, db: Session = Depends(get_db)):
    """切換司機停派狀態(value=true 停派 / false 啟用)。停派司機的車不納入自動派遣。"""
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Driver not found")
    obj.suspended = value
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{id}", status_code=204)
def delete_driver(id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Driver not found")
    crud.delete(db, obj)
