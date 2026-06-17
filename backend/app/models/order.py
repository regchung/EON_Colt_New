from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_order_no: Mapped[str | None] = mapped_column(String(40), index=True)  # 來源平台訂單編號(冪等)
    fleet: Mapped[str | None] = mapped_column(String(20), index=True)  # 車行/子車隊(集團統一派遣標記)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    pickup_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pickup_window_min: Mapped[int] = mapped_column(Integer, default=30)

    passenger_name: Mapped[str | None] = mapped_column(String(50))
    passenger_phone: Mapped[str | None] = mapped_column(String(30))

    pickup_address: Mapped[str] = mapped_column(Text)
    pickup_lng: Mapped[float | None] = mapped_column(Float)
    pickup_lat: Mapped[float | None] = mapped_column(Float)
    dropoff_address: Mapped[str] = mapped_column(Text)
    dropoff_lng: Mapped[float | None] = mapped_column(Float)
    dropoff_lat: Mapped[float | None] = mapped_column(Float)

    pax: Mapped[int] = mapped_column(Integer, default=1)
    vehicle_type: Mapped[str] = mapped_column(String(10), default="normal")  # welfare|normal
    need_wheelchair: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_pool: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default="imported", index=True)
    assigned_vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL")
    )
    dispatch_seq: Mapped[int | None] = mapped_column(Integer)   # 該車的派遣順序
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 預計到達上車點

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
