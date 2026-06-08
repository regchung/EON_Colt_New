"""排班產生的路線停靠點(供地圖視覺化與司機路單)。"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RouteStop(Base):
    __tablename__ = "route_stop"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer)              # 該車路線內的順序
    kind: Mapped[str] = mapped_column(String(10))          # start | pickup | delivery | end
    order_id: Mapped[int | None] = mapped_column(Integer)
    lng: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    address: Mapped[str | None] = mapped_column(String(500))
