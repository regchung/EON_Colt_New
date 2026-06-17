"""系統參數設定 CRUD(限系統管理者)。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.app_setting import AppSetting
from app.models.user import User
from app.schemas.setting import SettingCreate, SettingOut, SettingUpdate
from app.services import settings as settings_svc

router = APIRouter(prefix="/settings", tags=["settings"])

_VALID_TYPES = {"str", "int", "float", "bool"}


@router.get("", response_model=list[SettingOut])
def list_settings(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """列出所有參數(會先補齊預設值)。"""
    settings_svc.seed_defaults(db)
    return settings_svc.list_all(db)


@router.post("", response_model=SettingOut, status_code=201)
def create_setting(
    body: SettingCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)
):
    if body.value_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail="value_type 須為 str/int/float/bool")
    if db.get(AppSetting, body.key):
        raise HTTPException(status_code=409, detail="參數 key 已存在")
    row = AppSetting(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{key}", response_model=SettingOut)
def update_setting(
    key: str, body: SettingUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)
):
    if body.value_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail="value_type 須為 str/int/float/bool")
    row = db.get(AppSetting, key)
    if row is None:
        raise HTTPException(status_code=404, detail="參數不存在")
    for f, v in body.model_dump().items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{key}")
def delete_setting(key: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row = db.get(AppSetting, key)
    if row is None:
        raise HTTPException(status_code=404, detail="參數不存在")
    db.delete(row)
    db.commit()
    return {"deleted": key}
