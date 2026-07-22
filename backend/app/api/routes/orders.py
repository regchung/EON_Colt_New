import json
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from sqlalchemy import func, or_, select

from app.core.config import settings
from app.crud.order import order as crud
from app.db.session import get_db
from app.models.order import Order
from app.schemas.order import OrderCreate, OrderOut, OrderUpdate
from app.services import doc_ingest
from app.services import daifong_importer
from app.services.geocode import geocode
from app.services.importer import parse_orders

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/stats")
def order_stats(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """儀表板用：訂單總數、一般訂單、候補成功數、候補成功率（自動派遣結果）。
    預設為今日；可傳 date_from / date_to 查區間。"""
    from datetime import date as date_cls
    if date_from is None and date_to is None:
        date_from = date_to = date_cls.today()

    def _q():
        q = select(func.count()).select_from(Order)
        if date_from:
            q = q.where(Order.service_date >= date_from)
        if date_to:
            q = q.where(Order.service_date <= date_to)
        return q

    total      = db.scalar(_q()) or 0
    # 已派遣（scheduled / ongoing / done）
    dispatched = db.scalar(_q().where(Order.status.in_(['scheduled', 'ongoing', 'done']))) or 0
    # 尚未派遣（imported）
    unassigned = db.scalar(_q().where(Order.status == 'imported')) or 0
    # 取消 / 其他
    other      = total - dispatched - unassigned

    standby_total   = db.scalar(_q().where(Order.booking_source.like('%候補%'))) or 0
    standby_success = db.scalar(
        _q().where(Order.booking_source.like('%候補%'))
            .where(Order.status.in_(['scheduled', 'ongoing', 'done']))
    ) or 0
    normal        = total - standby_total
    rate          = round(standby_success / standby_total * 100, 1) if standby_total else 0
    dispatch_rate = round(dispatched / total * 100, 1) if total else 0

    return {
        "date_from":       date_from.isoformat() if date_from else None,
        "date_to":         date_to.isoformat()   if date_to   else None,
        "total":           total,
        "dispatched":      dispatched,
        "unassigned":      unassigned,
        "other":           other,
        "dispatch_rate":   dispatch_rate,
        "normal":          normal,
        "standby_total":   standby_total,
        "standby_success": standby_success,
        "standby_rate":    rate,
    }

TEMPLATE_CSV = (
    "服務日期,上車時間,彈性,乘客姓名,電話,上車地址,下車地址,人數,車種,輪椅,共乘,備註\n"
    "2026/06/10,09:00,30,王小明,0912345678,台北市信義區市府路1號,新北市板橋區縣民大道二段7號,1,福祉車,Y,N,需輪椅升降\n"
    "2026/06/10,09:30,20,陳大華,0922333444,台北市大安區忠孝東路四段1號,台北市中山區南京東路三段1號,2,一般車,N,Y,\n"
)


@router.get("", response_model=list[OrderOut])
def list_orders(
    skip: int = 0,
    limit: int = 500,
    service_date: date | None = None,
    status: str | None = None,
    vehicle_type: str | None = None,
    db: Session = Depends(get_db),
):
    from sqlalchemy import select, desc
    from app.models.order import Order as OrderModel
    stmt = select(OrderModel)
    if service_date:
        stmt = stmt.where(OrderModel.service_date == service_date)
    if status:
        stmt = stmt.where(OrderModel.status == status)
    if vehicle_type:
        stmt = stmt.where(OrderModel.vehicle_type == vehicle_type)
    stmt = stmt.order_by(desc(OrderModel.service_date), desc(OrderModel.pickup_time)).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


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
        headers={"Content-Disposition": "attachment; filename=dr_fish_import_template.csv"},
    )


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/import")
async def import_orders(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """批次匯入車行訂單(.xlsx / .csv)，以 SSE 串流回傳逐列進度。"""
    content = await file.read()
    filename = file.filename or ""

    async def generate():
        # 解析檔案
        try:
            payloads, errors = parse_orders(filename, content)
        except ValueError as e:
            yield _sse({"type": "error", "message": str(e)})
            return

        total = len(payloads) + len(errors)
        yield _sse({"type": "start", "total": total, "filename": filename})

        created_orders: list[Order] = []
        created = 0

        # 逐列寫入 DB
        for i, payload in enumerate(payloads):
            try:
                order = crud.create(db, OrderCreate(**payload))
                created_orders.append(order)
                created += 1
            except (ValidationError, Exception) as e:  # noqa: BLE001
                errors.append({"row": f"payload#{i + 1}", "error": str(e)})
            yield _sse({"type": "progress", "phase": "import",
                        "current": i + 1, "total": len(payloads),
                        "created": created})

        # 地理編碼（逐筆串流進度）
        geo_done = 0
        geo_failed = 0
        geo_total = len(created_orders)
        if geo_total:
            yield _sse({"type": "geocode_start", "total": geo_total})
            for idx, o in enumerate(created_orders):
                r = _geocode_order(db, o)
                if r["pickup"]["found"] and r["dropoff"]["found"]:
                    geo_done += 1
                else:
                    geo_failed += 1
                yield _sse({"type": "progress", "phase": "geocode",
                            "current": idx + 1, "total": geo_total,
                            "done": geo_done, "failed": geo_failed})

        yield _sse({
            "type": "done",
            "filename": filename,
            "total_rows": total,
            "created": created,
            "failed": len(errors),
            "geocoded": {"done": geo_done, "failed": geo_failed},
            "errors": errors,
        })

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


@router.post("/import-doc")
async def import_doc(
    file: UploadFile = File(...),
    service_date: date | None = None,
    db: Session = Depends(get_db),
):
    """AI 文件智慧匯入:上傳 PDF/Word/Excel/CSV/文字 → Claude 抽取訂單 → 建單 + 地理編碼。

    ⚠️ 會將文件原文(可能含個資)送往 Claude API 抽取;正式處理真實 PII 前應改地端模型。
    service_date 為「文件未標明日期時」的預設服務日期。
    """
    content = await file.read()
    filename = file.filename or ""
    try:
        text = doc_ingest.extract_text(filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=400, detail="未設定 ANTHROPIC_API_KEY,無法使用文件智慧匯入")

    default_date = service_date.isoformat() if service_date else None
    try:
        payloads, errors, _raw = doc_ingest.extract_orders(text, default_date)
    except Exception as e:  # noqa: BLE001 — Claude/網路錯誤統一回 502
        raise HTTPException(status_code=502, detail=f"AI 抽取失敗:{e}")

    created_orders: list[Order] = []
    created = 0
    for i, payload in enumerate(payloads):
        try:
            created_orders.append(crud.create(db, OrderCreate(**payload)))
            created += 1
        except (ValidationError, Exception) as exc:  # noqa: BLE001
            errors.append({"row": f"order#{i + 1}", "error": str(exc)})

    geo_done = geo_failed = 0
    for o in created_orders:
        r = _geocode_order(db, o)
        if r["pickup"]["found"] and r["dropoff"]["found"]:
            geo_done += 1
        else:
            geo_failed += 1

    return {
        "filename": filename,
        "extracted": len(payloads),
        "created": created,
        "failed": len(errors),
        "geocoded": {"done": geo_done, "failed": geo_failed},
        "errors": errors,
        "preview": [
            {"service_date": o.service_date.isoformat(),
             "pickup_time": o.pickup_time.strftime("%Y-%m-%d %H:%M") if o.pickup_time else None,
             "passenger_name": o.passenger_name,
             "pickup_address": o.pickup_address, "dropoff_address": o.dropoff_address,
             "vehicle_type": o.vehicle_type, "pax": o.pax}
            for o in created_orders[:20]
        ],
    }


@router.post("/import-daifong")
async def import_daifong(
    file: UploadFile = File(...),
    replace_date: bool = False,
    db: Session = Depends(get_db),
):
    """大豐班表 Excel 匯入。
    replace_date=true：先刪除相同服務日期的既有訂單，再匯入（冪等）。
    """
    content = await file.read()
    try:
        result = daifong_importer.import_excel(db, content, replace_date=replace_date)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"匯入失敗：{e}")
    return result


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


@router.post("/geo-audit")
def geo_audit(service_date: date, apply: bool = True, db: Session = Depends(get_db)):
    """地址編碼勘誤:某日缺座標或離營運區>40km(疑似編到他縣市)的訂單,
    產生修正版地址重編、挑最靠營運區的結果採用並回寫(apply=False 為 dry-run)。"""
    from app.services import geo_audit as ga
    return ga.audit_day(db, service_date, apply=apply)


from app.models.vehicle import Vehicle  # noqa: E402


@router.post("/{id}/assign", response_model=OrderOut)
def assign_order(id: int, vehicle_id: int, db: Session = Depends(get_db)):
    """手動指派訂單給指定車輛(採用區域親和建議用)。狀態轉為 scheduled。"""
    o = crud.get(db, id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(status_code=404, detail="車輛不存在")
    # 該車當日下一個派遣順序
    next_seq = (db.scalar(
        select(func.max(Order.dispatch_seq))
        .where(Order.assigned_vehicle_id == vehicle_id, Order.service_date == o.service_date)
    ) or 0) + 1
    o.assigned_vehicle_id = vehicle_id
    o.status = "scheduled"
    o.dispatch_seq = next_seq
    db.commit()
    db.refresh(o)
    return o


ALLOWED_STATUS = {"imported", "scheduled", "ongoing", "done", "canceled"}


@router.post("/{id}/unassign", response_model=OrderOut)
def unassign_order(id: int, db: Session = Depends(get_db)):
    """解除指派(拖回未指派):回到 imported、清除車輛/順序/ETA。"""
    o = crud.get(db, id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    o.status = "imported"
    o.assigned_vehicle_id = None
    o.dispatch_seq = None
    o.eta = None
    db.commit()
    db.refresh(o)
    return o


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
