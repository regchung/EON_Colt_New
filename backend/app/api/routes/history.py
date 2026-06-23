"""人工派遣歷史匯入與檢視(需登入)。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.dispatch_history import DispatchHistory
from app.services.history_import import import_history
from app.services.schedule_import import import_schedule

router = APIRouter(prefix="/history", tags=["history"])


@router.post("/import")
async def import_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """匯入長照車隊平台匯出檔(.xls/.xlsx):建訂單 + 派遣歷史 + 自建車/司機 + 灌地址簿。"""
    content = await file.read()
    try:
        return import_history(db, content, file.filename or "")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"匯入失敗:{e}")


@router.post("/import-schedule")
async def import_schedule_file(
    file: UploadFile = File(...),
    replace_date: bool = True,
    db: Session = Depends(get_db),
):
    """匯入車隊「班表」(人工派遣結果):每列含乘客+起迄+時段+指派車牌/駕駛
    → 建訂單(done)+ 人工派遣歷史(已轉至正式單)+ 地理編碼,供逐車對比。
    replace_date=True 時,匯入前先清空班表內各服務日期的既有訂單/歷史。
    """
    content = await file.read()
    try:
        rep = import_schedule(db, content, file.filename or "", replace_date=replace_date)
        if rep.get("error"):
            raise HTTPException(status_code=400, detail=rep["error"])
        return rep
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"匯入失敗:{e}")


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    """歷史統計:總筆數、各駕駛/派單員/區域分布(供經驗分析雛形)。"""
    total = db.scalar(select(func.count()).select_from(DispatchHistory)) or 0

    def group(col):
        return dict(db.execute(
            select(col, func.count()).group_by(col).order_by(func.count().desc())
        ).all())

    return {
        "total": total,
        "by_driver": group(DispatchHistory.driver_name),
        "by_dispatcher": group(DispatchHistory.dispatcher),
        "by_pickup_town": group(DispatchHistory.pickup_town),
        "by_dropoff_town": group(DispatchHistory.dropoff_town),
        "by_status": group(DispatchHistory.status),
    }
