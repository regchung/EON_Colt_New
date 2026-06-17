"""人工派遣歷史(由車隊平台匯出檔匯入)。保留作為經驗知識與人工 vs 自動對比的素材。"""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DispatchHistory(Base):
    __tablename__ = "dispatch_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_order_no: Mapped[str | None] = mapped_column(String(40), index=True)
    fleet: Mapped[str | None] = mapped_column(String(20), index=True)  # 車行/子車隊
    service_date: Mapped[date | None] = mapped_column(Date, index=True)
    pickup_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 人工派遣結果(核心)
    plate: Mapped[str | None] = mapped_column(String(20), index=True)
    driver_name: Mapped[str | None] = mapped_column(String(50))
    driver_phone: Mapped[str | None] = mapped_column(String(30))
    dispatcher: Mapped[str | None] = mapped_column(String(50))  # 派單人員

    # 區域(供經驗分析)
    pickup_city: Mapped[str | None] = mapped_column(String(20))
    pickup_town: Mapped[str | None] = mapped_column(String(20))
    dropoff_city: Mapped[str | None] = mapped_column(String(20))
    dropoff_town: Mapped[str | None] = mapped_column(String(20))

    pickup_address: Mapped[str | None] = mapped_column(String(500))
    dropoff_address: Mapped[str | None] = mapped_column(String(500))
    pickup_lng: Mapped[float | None] = mapped_column(Float)
    pickup_lat: Mapped[float | None] = mapped_column(Float)
    dropoff_lng: Mapped[float | None] = mapped_column(Float)
    dropoff_lat: Mapped[float | None] = mapped_column(Float)

    vehicle_type_req: Mapped[str | None] = mapped_column(String(40))  # 長照車型要求
    pax: Mapped[int | None] = mapped_column(Integer)
    wheelchair_count: Mapped[int | None] = mapped_column(Integer)

    distance_m: Mapped[float | None] = mapped_column(Float)
    est_minutes: Mapped[float | None] = mapped_column(Float)
    service_minutes: Mapped[float | None] = mapped_column(Float)

    fare_negotiated: Mapped[float | None] = mapped_column(Float)
    subsidy: Mapped[float | None] = mapped_column(Float)
    self_pay: Mapped[float | None] = mapped_column(Float)

    status: Mapped[str | None] = mapped_column(String(30))         # CurrentStatus
    order_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    op_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    raw: Mapped[dict | None] = mapped_column(JSON)  # 整列保留(已去除身分證號)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
