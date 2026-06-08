from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


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
    status: str = "imported"
    assigned_vehicle_id: int | None = None


class OrderCreate(OrderBase):
    pass


class OrderUpdate(OrderBase):
    pass


class OrderOut(OrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    dispatch_seq: int | None = None
    eta: datetime | None = None
    created_at: datetime
