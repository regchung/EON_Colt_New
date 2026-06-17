"""系統參數設定(key-value):派遣營運規則等可由管理者調整的參數。"""
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(10), default="str")  # str|int|float|bool
    group: Mapped[str | None] = mapped_column(String(30))               # 分組(派遣規則/共乘/營運…)
    label: Mapped[str | None] = mapped_column(String(80))               # 顯示名稱
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
