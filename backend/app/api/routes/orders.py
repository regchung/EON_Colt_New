from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from sqlalchemy import or_, select

from app.core.config import settings
from app.crud.order import order as crud
from app.db.session import get_db
from app.models.order import Order
from app.schemas.order import OrderCreate, OrderOut, OrderUpdate
from app.services.geocode import geocode
from app.services.importer import parse_orders

router = APIRouter(prefix="/orders", tags=["orders"])

TEMPLATE_CSV = (
    "服務日期,上車時間,彈性,乘客姓名,電話,上車地址,下車地址,人數,車種,輪椅,共乘,備註\n"
    "2026/06/10,09:00,30,王小明,0912345678,台北市信義區市府路1號,新北市板橋區縣民大道二段7號,1,福祉車,Y,N,需輪椅升降\n"
    "2026/06/10,09:30,20,陳大華,0922333444,台北市大安區忠孝東路四段1號,台北市中山區南京東路三段1號,2,一般車,N,Y,\n"
)


@router.get("", response_model=list[OrderOut])
def list_orders(
    skip: int = 0,
    limit: int = 100,
    service_date: date | None = None,
    status: str | None = None,
    vehicle_type: str | None = None,
    db: Session = Depends(get_db),
):
    return crud.list(
        db,
        skip=skip,
        limit=limit,
        service_date=service_date,
        status=status,
        vehicle_type=vehicle_type,
    )


@router.post("", response_model=OrderOut, status_code=201)
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    return crud.create(db, payload)


@router.get("/import/template")
def download_template():
    """下載車行匯入範本(CSV,UTF-8 BOM 以利 Excel 開啟)。"""
    body = ("﻿" + TEMPLATE_CSV).encode("utf-8")
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=smartcar_import_template.csv"},
    )


@router.post("/import")
async def import_orders(
    file: UploadFile = File(...),
    geocode: bool = True,
    db: Session = Depends(get_db),
):
    """批次匯入車行訂單(.xlsx / .csv)。預設匯入後自動地理編碼(走地址簿快取)。"""
    content = await file.read()
    try:
        payloads, errors = parse_orders(file.filename or "", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    created_orders: list[Order] = []
    for i, payload in enumerate(payloads):
        try:
            created_orders.append(crud.create(db, OrderCreate(**payload)))
        except (ValidationError, Exception) as e:  # noqa: BLE001
            errors.append({"row": f"payload#{i + 1}", "error": str(e)})

    geocoded = {"done": 0, "failed": 0}
    if geocode:
        for o in created_orders:
            r = _geocode_order(db, o)
            if r["pickup"]["found"] and r["dropoff"]["found"]:
                geocoded["done"] += 1
            else:
                geocoded["failed"] += 1

    return {
        "filename": file.filename,
        "total_rows": len(payloads) + len([e for e in errors if isinstance(e.get("row"), int)]),
        "created": len(created_orders),
        "failed": len(errors),
        "geocoded": geocoded if geocode else None,
        "errors": errors,
    }


def _geocode_order(db: Session, o: Order) -> dict:
    """對單筆訂單的上/下車地址做地理編碼並更新座標。回傳該筆結果摘要。"""
    pk = geocode(db, o.pickup_address)
    dp = geocode(db, o.dropoff_address)
    o.pickup_lng, o.pickup_lat = pk.lng, pk.lat
    o.dropoff_lng, o.dropoff_lat = dp.lng, dp.lat
    db.commit()
    return {
        "id": o.id,
        "pickup": {"found": pk.found, "precision": pk.precision},
        "dropoff": {"found": dp.found, "precision": dp.precision},
    }


@router.post("/{id}/geocode")
def geocode_order(id: int, db: Session = Depends(get_db)):
    """地理編碼單筆訂單。"""
    o = crud.get(db, id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    return _geocode_order(db, o)


@router.post("/geocode-pending")
def geocode_pending(limit: int | None = None, db: Session = Depends(get_db)):
    """批次地理編碼:處理尚缺座標的訂單(上車或下車經度為空)。"""
    cap = limit or settings.GEOCODE_BATCH_LIMIT
    stmt = (
        select(Order)
        .where(or_(Order.pickup_lng.is_(None), Order.dropoff_lng.is_(None)))
        .order_by(Order.id)
        .limit(cap)
    )
    orders = list(db.scalars(stmt).all())
    results = [_geocode_order(db, o) for o in orders]
    failed = sum(
        1 for r in results if not r["pickup"]["found"] or not r["dropoff"]["found"]
    )
    return {
        "processed": len(results),
        "succeeded": len(results) - failed,
        "failed": failed,
        "results": results,
    }


ALLOWED_STATUS = {"imported", "scheduled", "ongoing", "done", "canceled"}


@router.post("/{id}/cancel", response_model=OrderOut)
def cancel_order(id: int, db: Session = Depends(get_db)):
    """取消訂單:標記 canceled 並清除派遣指派(下次排班會自動排除)。"""
    o = crud.get(db, id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    o.status = "canceled"
    o.assigned_vehicle_id = None
    o.dispatch_seq = None
    o.eta = None
    db.commit()
    db.refresh(o)
    return o


@router.post("/{id}/status", response_model=OrderOut)
def set_status(id: int, value: str, db: Session = Depends(get_db)):
    """變更訂單狀態(imported/scheduled/ongoing/done/canceled)。
    ongoing/done 視為已鎖定,重新排班時不會被更動。"""
    if value not in ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail=f"狀態須為 {ALLOWED_STATUS}")
    o = crud.get(db, id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    o.status = value
    db.commit()
    db.refresh(o)
    return o


@router.get("/{id}", response_model=OrderOut)
def get_order(id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Order not found")
    return obj


@router.put("/{id}", response_model=OrderOut)
def update_order(id: int, payload: OrderUpdate, db: Session = Depends(get_db)):
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Order not found")
    return crud.update(db, obj, payload)


@router.delete("/{id}", status_code=204)
def delete_order(id: int, db: Session = Depends(get_db)):
    obj = crud.get(db, id)
    if not obj:
        raise HTTPException(status_code=404, detail="Order not found")
    crud.delete(db, obj)
