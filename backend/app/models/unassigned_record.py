"""無法派遣(未派)訂單記錄。

由對比批次(comparison.run_batch)寫入:逐(日 × 訂單)記錄系統為何無法排入,
以及人工當時實際用哪台車執行;並提供行控回饋欄位,蒐集人為因素以協助日後學習。
"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UnassignedRecord(Base):
    __tablename__ = "unassigned_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    fleet: Mapped[str | None] = mapped_column(String(20), index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    source_order_no: Mapped[str | None] = mapped_column(String(40))

    # 系統推斷原因
    reason_code: Mapped[str] = mapped_column(String(20))   # out_of_hours/no_welfare/unroutable/infeasible
    reason_detail: Mapped[str | None] = mapped_column(String(200))
    window_min: Mapped[int | None] = mapped_column(Integer)

    # 人工派遣實際結果(供對照)
    human_plate: Mapped[str | None] = mapped_column(String(20))
    human_driver: Mapped[str | None] = mapped_column(String(50))

    # 行控回饋(協助系統學習)
    feedback_category: Mapped[str | None] = mapped_column(String(30))
    feedback_note: Mapped[str | None] = mapped_column(String(500))
    feedback_by: Mapped[str | None] = mapped_column(String(50))
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
