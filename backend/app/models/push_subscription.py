"""司機端 Web Push 訂閱(VAPID)。

每個瀏覽器/裝置在司機允許通知後,會產生一個 PushSubscription(endpoint + 金鑰),
存於此表。派遣有異動時,後端用 pywebpush 對該 endpoint 送推播。
以 endpoint 為唯一鍵(同裝置重訂只更新),可選綁定 driver_id。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PushSubscription(Base):
    __tablename__ = "push_subscription"
    __table_args__ = (UniqueConstraint("endpoint", name="uq_push_endpoint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), index=True, nullable=True
    )
    endpoint: Mapped[str] = mapped_column(Text, index=True)
    p256dh: Mapped[str] = mapped_column(Text)   # 客戶端公鑰
    auth: Mapped[str] = mapped_column(Text)     # 認證祕密
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
