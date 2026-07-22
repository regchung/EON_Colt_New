from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, field_validator

TW = timezone(timedelta(hours=8))   # 系統一律以台灣時間 +08 儲存上車/ETA


class OrderBase(BaseModel):
    service_date: date
    pickup_time: datetime
    pickup_window_min: int = 30
    passenger_name: str | None = None
    passenger_phone: str | None = None
    pickup_address: str
    pickup_lng: float | None = None
    pickup_lat: float | None = None
    dropoff_address: str
    dropoff_lng: float | None = None
    dropoff_lat: float | None = None
    pax: int = 1
    vehicle_type: str = "normal"  # 'welfare' | 'normal'
    need_wheelchair: bool = False
    allow_pool: bool = True
    note: str | None = None
    payment_type: str | None = None    # subsidy=補助 / self=自費
    order_nature: str | None = None    # 性質
    customer_region: str | None = None # 客戶所在地區
    eligibility: str | None = None     # 身份資格
    mileage: float | None = None       # 里程
    fare: int | None = None            # 車資
    companion_fee: int | None = None   # 陪同金額
    self_pay_amount: int | None = None # 自付金額
    subsidy_balance: str | None = None  # 補助餘額
    booking_source: str | None = None  # 預約方式(電話/LINE/L包/包月/候補/共乘)
    id_number: str | None = None       # 身分證字號
    dropoff_time: datetime | None = None  # 客下車時間
    assigned_plate: str | None = None  # 車號文字(匯入留存)
    driver_name: str | None = None     # 司機姓名
    operator: str | None = None        # 填單人
    status: str = "imported"
    assigned_vehicle_id: int | None = None

    @field_validator("pickup_time")
    @classmethod
    def _ensure_tw(cls, v: datetime) -> datetime:
        """無時區的上車時間視為台灣本地時間,補上 +08;已帶時區者原樣保留。

        手動建單(datetime-local 無時區)與 AI 文件匯入(字串無 offset)皆走此處,
        避免被當成 UTC 而落差 8 小時(造成派遣服務窗誤判)。
        """
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=TW)
        return v


class OrderCreate(OrderBase):
    pass


class OrderUpdate(OrderBase):
    pass


class OrderOut(OrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dispatch_seq: int | None = None
    eta: datetime | None = None
    support_fleet: str | None = None   # 跨車行支援:出車車輛所屬車行(≠ fleet 時)
    dispatch_note: str | None = None   # 支援原因白話
    created_at: datetime
