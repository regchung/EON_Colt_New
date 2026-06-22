"""車隊名冊匯入(司機/車輛主檔;需登入)。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
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
