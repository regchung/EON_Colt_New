"""人工 vs 自動(VROOM)逐日對比結果。"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DispatchComparison(Base):
    __tablename__ = "dispatch_comparison"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fleet: Mapped[str | None] = mapped_column(String(20), index=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    window_min: Mapped[int] = mapped_column(Integer, default=30)

    n_orders: Mapped[int] = mapped_column(Integer)          # 當日成行單數
    human_vehicles: Mapped[int] = mapped_column(Integer)    # 人工用車數
    vroom_vehicles: Mapped[int] = mapped_column(Integer)    # VROOM 用車數
    vroom_unassigned: Mapped[int] = mapped_column(Integer)  # VROOM 無法排入(時間窗)
    saved_vehicles: Mapped[int] = mapped_column(Integer)    # 省下車數(人工-VROOM)

    human_distance_m: Mapped[float | None] = mapped_column(Float)   # 人工里程(來源檔)
    human_minutes: Mapped[float | None] = mapped_column(Float)      # 人工預估分鐘(來源檔)
    vroom_drive_sec: Mapped[float | None] = mapped_column(Float)    # VROOM 總行駛秒(OSRM)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
