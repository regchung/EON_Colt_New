"""車行(=區域)校準:每趟上下車作業時間、速度係數,從歷史數據校準。

每趟工時不再用全域固定 40 分,而是依「車行 × 是否福祉單」用該車行自己的
歷史(背靠背連續趟反推)校準;樣本不足者退回全域預設(fleet='*')。
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FleetCalibration(Base):
    __tablename__ = "fleet_calibration"

    fleet: Mapped[str] = mapped_column(String(30), primary_key=True)  # 車行;'*' = 全域預設
    service_normal_sec: Mapped[int] = mapped_column(Integer, default=2400)   # 一般單每趟作業(setup+teardown)
    service_welfare_sec: Mapped[int] = mapped_column(Integer, default=2400)  # 福祉單每趟作業
    speed_factor: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")  # OSRM 車程乘數(>1=該區較慢)
    samples: Mapped[int] = mapped_column(Integer, default=0)          # 校準所用背靠背趟對數(信心)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
