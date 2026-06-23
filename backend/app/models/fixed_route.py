"""固定行程指定司機規則。

行控設定「某地點/個案固定由某司機執行」(可含時段早/午/晚分流)。
派遣時把符合 keyword 的訂單釘給指定司機(後續整合);本表先提供 CRUD 與保存。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FixedRoute(Base):
    __tablename__ = "fixed_route"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(60))          # 路線顯示名,如「成德國中-2」
    keyword: Mapped[str | None] = mapped_column(String(60), index=True)  # 地點匹配文字(可空),如「成德國中」「錸工廠」
    match_name: Mapped[str | None] = mapped_column(String(50))  # 指定乘客姓名(可空):比對訂單乘客姓名
    driver_name: Mapped[str] = mapped_column(String(50))    # 指定司機
    time_slot: Mapped[str] = mapped_column(String(20), default="全天")  # 全天/早/午/午後/早晚
    match_field: Mapped[str] = mapped_column(String(20), default="any")  # passenger/address/any
    fleet: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(200))

    # --- 既定區塊維護欄位(固定趟參數;供產生當日委派/對比釘車)---
    pickup_address: Mapped[str | None] = mapped_column(Text)     # 起點地址
    dropoff_address: Mapped[str | None] = mapped_column(Text)    # 迄點/目的地地址
    plate: Mapped[str | None] = mapped_column(String(20))        # 指定車牌(空則由司機解出)
    start_time: Mapped[str | None] = mapped_column(String(5))    # 起始時段 "HH:MM"
    occupancy_min: Mapped[int | None] = mapped_column(Integer)   # 整趟佔用時間(分);空則用 settings 估算
    pax: Mapped[int] = mapped_column(Integer, default=1)         # 乘客數(座位需求)
    vehicle_type: Mapped[str] = mapped_column(String(10), default="normal")  # normal|welfare
    wheelchair: Mapped[int] = mapped_column(Integer, default=0)  # 輪椅數
    allow_pool: Mapped[bool] = mapped_column(Boolean, default=False)  # 預設不可併(各釘各車)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
