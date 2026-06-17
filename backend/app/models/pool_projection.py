"""共乘增益投影:各車行『現況共乘 vs 推薦組全同意』的車日彙總(供報表/前端快速讀取)。

由 pool_suggest.project_and_store() 批次寫入(每車行一列),避免前端即時雙跑 VROOM。
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PoolProjection(Base):
    __tablename__ = "pool_projection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fleet: Mapped[str | None] = mapped_column(String(20), index=True)
    window_min: Mapped[int] = mapped_column(Integer, default=30)

    days: Mapped[int] = mapped_column(Integer)              # 有比對的營運日
    v_now: Mapped[int] = mapped_column(Integer)             # 現況(僅已同意者共乘)車日
    v_pool: Mapped[int] = mapped_column(Integer)            # 推薦組全同意後車日
    saved_vehicles: Mapped[int] = mapped_column(Integer)    # 額外可省車日(v_now - v_pool)
    ask_groups: Mapped[int] = mapped_column(Integer)        # 需徵詢的共乘組數

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
