"""地址簿:門牌正規化快取。

- AddressPoint:一個「校正後地址(門牌)」+ 座標(唯一)。
- AddressAlias:各種「原始描述」→ 對應的門牌。
  address_point_id 為 NULL 代表「查過但查無」,用來快取失敗、避免重複呼叫 Map8。
"""
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AddressPoint(Base):
    __tablename__ = "address_point"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    standardized_address: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    lng: Mapped[float] = mapped_column(Float)
    lat: Mapped[float] = mapped_column(Float)
    precision: Mapped[str | None] = mapped_column(String(10))   # Map8 level:1=門牌,4=道路...
    city: Mapped[str | None] = mapped_column(String(20))
    town: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(20))      # map8 | nominatim
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AddressAlias(Base):
    __tablename__ = "address_alias"

    raw_address: Mapped[str] = mapped_column(String(500), primary_key=True)
    address_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("address_point.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
