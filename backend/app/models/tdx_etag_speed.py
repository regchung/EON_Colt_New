"""TDX ETag 即時行程時間歷史資料。"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class TdxEtagSpeed(Base):
    __tablename__ = "tdx_etag_speed"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    etag_pair_id: Mapped[str] = mapped_column(String(50), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    space_mean_speed: Mapped[float | None] = mapped_column(Float)   # km/h, -99 stored as None
    travel_time: Mapped[int | None] = mapped_column(Integer)         # seconds, -99 stored as None
    vehicle_count: Mapped[int | None] = mapped_column(Integer)
    vehicle_type: Mapped[int | None] = mapped_column(Integer)        # 31=小型車, 32=大型車 etc.

    __table_args__ = (
        Index("ix_etag_speed_pair_time", "etag_pair_id", "collected_at"),
        Index("ix_etag_speed_collected_at", "collected_at"),
    )
