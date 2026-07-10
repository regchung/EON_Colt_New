from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    phone: Mapped[str | None] = mapped_column(String(30))
    license_no: Mapped[str | None] = mapped_column(String(30))
    home_fleet: Mapped[str | None] = mapped_column(String(20))  # 最常所屬車行
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # 停派:不納入自動派遣
