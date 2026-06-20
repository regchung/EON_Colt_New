"""Web Push 推播服務(VAPID / pywebpush)。

- save_subscription:司機瀏覽器訂閱 → upsert(以 endpoint 為鍵)。
- remove_subscription:退訂。
- send_to_driver / send_to_subscription:送推播;對失效訂閱(404/410)自動清除。

無 VAPID 金鑰時優雅降級(回 sent=0,不丟例外),維持「精簡、可選功能」原則。
"""
from __future__ import annotations

import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.push_subscription import PushSubscription


def save_subscription(db: Session, sub: dict, driver_id: int | None = None,
                      user_agent: str | None = None) -> PushSubscription:
    """upsert 一筆訂閱。sub 形如 {endpoint, keys:{p256dh, auth}}。"""
    endpoint = sub["endpoint"]
    keys = sub.get("keys", {})
    row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if row is None:
        row = PushSubscription(endpoint=endpoint)
        db.add(row)
    row.p256dh = keys.get("p256dh", "")
    row.auth = keys.get("auth", "")
    row.driver_id = driver_id
    row.user_agent = (user_agent or "")[:300] or None
    db.commit()
    db.refresh(row)
    return row


def remove_subscription(db: Session, endpoint: str) -> int:
    n = db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint)).rowcount
    db.commit()
    return n or 0


def _send_one(db: Session, row: PushSubscription, payload: dict) -> bool:
    """送單筆;失效(404/410)即刪除。回傳是否成功。"""
    from pywebpush import WebPushException, webpush  # 延遲匯入,未裝/未啟用時不影響其他功能
    try:
        webpush(
            subscription_info={
                "endpoint": row.endpoint,
                "keys": {"p256dh": row.p256dh, "auth": row.auth},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            timeout=10,
        )
        return True
    except WebPushException as e:  # noqa: BLE001
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):   # 訂閱已失效 → 清除
            db.execute(delete(PushSubscription).where(PushSubscription.id == row.id))
            db.commit()
        return False


def send_to_subscriptions(db: Session, rows: list[PushSubscription], title: str,
                          body: str, url: str = "/", tag: str | None = None) -> int:
    if not settings.push_enabled:
        return 0
    payload = {"title": title, "body": body, "url": url, "tag": tag}
    return sum(1 for r in rows if _send_one(db, r, payload))


def send_to_driver(db: Session, driver_id: int, title: str, body: str,
                   url: str = "/", tag: str | None = None) -> int:
    """送給某司機所有裝置。回傳成功筆數。"""
    rows = list(db.scalars(select(PushSubscription).where(
        PushSubscription.driver_id == driver_id)).all())
    return send_to_subscriptions(db, rows, title, body, url, tag)


def broadcast(db: Session, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    rows = list(db.scalars(select(PushSubscription)).all())
    return send_to_subscriptions(db, rows, title, body, url, tag)
