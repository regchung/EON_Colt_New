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


# 派遣積極度預設(循序漸進讓使用者接受自動派遣):一鍵設 service_time_factor + pickup_window_min
DISPATCH_PRESETS = {
    1: {"label": "① 貼近人工", "service_time_factor": "2.0", "pickup_window_min": "9",
        "desc": "自動派遣結果最接近人工(省車最少),供初期建立信任"},
    2: {"label": "② 溫和優化", "service_time_factor": "1.55", "pickup_window_min": "9",
        "desc": "現行預設,開始展現省車效益(約省 15%)"},
    3: {"label": "③ 積極省車", "service_time_factor": "1.0", "pickup_window_min": "30",
        "desc": "成熟後收割最大省車(約省 30%)"},
}


@router.get("/dispatch-presets")
def dispatch_presets(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """派遣積極度預設清單 + 目前值。"""
    cur = {"service_time_factor": settings_svc.get(db, "service_time_factor"),
           "pickup_window_min": settings_svc.get(db, "pickup_window_min")}
    active = next((s for s, p in DISPATCH_PRESETS.items()
                   if str(p["service_time_factor"]) == str(cur["service_time_factor"])
                   and str(p["pickup_window_min"]) == str(cur["pickup_window_min"])), None)
    return {"current": cur, "active_stage": active,
            "presets": [{"stage": s, **p} for s, p in DISPATCH_PRESETS.items()]}


@router.post("/dispatch-preset")
def apply_dispatch_preset(stage: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """套用派遣積極度預設(stage 1/2/3):設 service_time_factor + pickup_window_min。"""
    p = DISPATCH_PRESETS.get(stage)
    if not p:
        raise HTTPException(status_code=400, detail="stage 須為 1/2/3")
    settings_svc.seed_defaults(db)
    for key in ("service_time_factor", "pickup_window_min"):
        row = db.get(AppSetting, key)
        if row:
            row.value = p[key]
    db.commit()
    return {"applied_stage": stage, "label": p["label"],
            "service_time_factor": p["service_time_factor"], "pickup_window_min": p["pickup_window_min"]}
