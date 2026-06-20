"""司機端 Web Push 訂閱與測試端點。

- GET  /push/public-key   取得 VAPID 公鑰(前端 service worker 訂閱用)
- POST /push/subscribe    儲存訂閱(瀏覽器允許通知後)
- POST /push/unsubscribe  移除訂閱
- POST /push/test         送一則測試推播(驗證鏈路)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services import push as push_svc

router = APIRouter(prefix="/push", tags=["push"])


class SubscribeIn(BaseModel):
    subscription: dict          # {endpoint, keys:{p256dh, auth}}
    driver_id: int | None = None


class UnsubscribeIn(BaseModel):
    endpoint: str


class TestIn(BaseModel):
    driver_id: int | None = None


@router.get("/public-key")
def public_key() -> dict:
    return {"public_key": settings.VAPID_PUBLIC_KEY, "enabled": settings.push_enabled}


@router.post("/subscribe")
def subscribe(body: SubscribeIn, request: Request, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> dict:
    if not body.subscription.get("endpoint"):
        raise HTTPException(400, "缺少 subscription.endpoint")
    row = push_svc.save_subscription(
        db, body.subscription, driver_id=body.driver_id,
        user_agent=request.headers.get("user-agent"),
    )
    return {"ok": True, "id": row.id, "enabled": settings.push_enabled}


@router.post("/unsubscribe")
def unsubscribe(body: UnsubscribeIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict:
    n = push_svc.remove_subscription(db, body.endpoint)
    return {"ok": True, "removed": n}


@router.post("/test")
def test_push(body: TestIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> dict:
    if not settings.push_enabled:
        raise HTTPException(400, "未設定 VAPID 金鑰,推播停用")
    if body.driver_id is not None:
        sent = push_svc.send_to_driver(db, body.driver_id, "SmartCar 測試推播",
                                       "推播鏈路正常 ✓", url="/driver")
    else:
        sent = push_svc.broadcast(db, "SmartCar 測試推播", "推播鏈路正常 ✓", url="/driver")
    return {"ok": True, "sent": sent}
