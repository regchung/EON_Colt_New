"""車隊名冊匯入(司機/車輛主檔;需登入)。"""
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.daily_roster_import import import_daily_roster
from app.services.fleet_import import import_fleet, reconcile_fleet

router = APIRouter(prefix="/fleet", tags=["fleet"])


@router.post("/import")
async def import_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """匯入車隊名冊(.xls/.xlsx):回填真實可載客數、福祉能力、出車起點/收車終點。

    以車牌冪等:既有車輛更新、未見車輛新增;司機以姓名 upsert 並綁定車輛。
    """
    content = await file.read()
    try:
        return import_fleet(db, content, file.filename or "")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"匯入失敗:{e}")


@router.post("/reconcile")
async def reconcile_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """依名冊對帳:檔內車牌/姓名→啟用,不在檔內的車輛/司機→停派(不納入自動派遣)。"""
    content = await file.read()
    try:
        return reconcile_fleet(db, content, file.filename or "")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"對帳失敗:{e}")


@router.post("/daily-roster")
async def daily_roster_upload(
    file: UploadFile = File(...),
    service_date: date = Query(..., description="服務日期 YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """每日出勤名冊上傳:設定指定日出勤車輛/司機/班別時段。

    - 名冊內車輛 → shift_exception(available=True,套用工作時段)+ 更新座位/輪椅/車輛來源
    - 名冊外 active 車輛 → shift_exception(available=False,當日停派)
    - 每列司機+車輛 → driver_vehicle_assignment(當日配對)
    """
    content = await file.read()
    try:
        return import_daily_roster(db, content, file.filename or "", service_date)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"每日名冊上傳失敗:{e}")
