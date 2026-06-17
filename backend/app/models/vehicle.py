from datetime import time

from sqlalchemy import Boolean, Float, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate: Mapped[str | None] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(10), default="normal")  # 'welfare' | 'normal'
    seats: Mapped[int] = mapped_column(Integer, default=4)
    shift_start: Mapped[time | None] = mapped_column(Time)
    shift_end: Mapped[time | None] = mapped_column(Time)
    depot_lng: Mapped[float | None] = mapped_column(Float)
    depot_lat: Mapped[float | None] = mapped_column(Float)
    home_fleet: Mapped[str | None] = mapped_column(String(20))  # 最常所屬車行(共用車池,僅標記)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
