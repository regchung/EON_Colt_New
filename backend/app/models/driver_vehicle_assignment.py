"""當日駕駛-車輛指派(處理司機輪車:某日某司機開哪台)。

優先於 Driver.vehicle_id 預設車;由 driver_resolve.resolve(name, date) 讀取。
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DriverVehicleAssignment(Base):
    __tablename__ = "driver_vehicle_assignment"
    __table_args__ = (UniqueConstraint("service_date", "driver_id", name="uq_dva_date_driver"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    note: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
