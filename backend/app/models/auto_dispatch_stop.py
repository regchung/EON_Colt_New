"""自動派遣停靠明細(對比引擎 dry-run 的每車每停靠點,持久化供稽核/檢視)。

由 comparison.persist_day 每次跑對比(自動派遣)時寫入;結構近似 route_stop,
另帶「在車人數 occupancy」與「跨車行支援 is_support」。與人工結果(dispatch_history
／route_stop)對照齊全,免每次即時重算。
"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AutoDispatchStop(Base):
    __tablename__ = "auto_dispatch_stop"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    fleet: Mapped[str | None] = mapped_column(String(20), index=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, index=True)
    plate: Mapped[str | None] = mapped_column(String(20))
    seq: Mapped[int] = mapped_column(Integer)            # 該車路線內順序
    kind: Mapped[str] = mapped_column(String(10))        # pickup | delivery
    order_id: Mapped[int | None] = mapped_column(Integer)
    lng: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occupancy: Mapped[int | None] = mapped_column(Integer)     # 此停靠後在車人數
    is_support: Mapped[bool] = mapped_column(Boolean, default=False)  # 出車車行 ≠ 訂單車行
    window_min: Mapped[int | None] = mapped_column(Integer)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
