"""班表:週期班表(ShiftPattern)+ 例外(ShiftException)。

以車輛為單位(該車所綁司機之出勤)。即時派遣只納入「當日 on-duty」的車。
可用性解析優先序:當日例外 > 週期班表 > (無資料→保守視為不可用)。
"""
from datetime import date, time

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ShiftPattern(Base):
    """每車的常態上班日(weekday 0=週一 … 6=週日);時段可空(空=用服務時段)。"""
    __tablename__ = "shift_pattern"
    __table_args__ = (UniqueConstraint("vehicle_id", "weekday", name="uq_shift_pattern_veh_wd"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)  # 0=Mon … 6=Sun
    shift_start: Mapped[time | None] = mapped_column(Time)
    shift_end: Mapped[time | None] = mapped_column(Time)


class ShiftException(Base):
    """單日例外:available=False 表請假/維修(當日不出勤);True 表臨時加班。"""
    __tablename__ = "shift_exception"
    __table_args__ = (UniqueConstraint("vehicle_id", "ex_date", name="uq_shift_exc_veh_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    ex_date: Mapped[date] = mapped_column(Date, index=True)
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    shift_start: Mapped[time | None] = mapped_column(Time)
    shift_end: Mapped[time | None] = mapped_column(Time)
    reason: Mapped[str | None] = mapped_column(String(50))
