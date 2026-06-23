from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FixedRouteBase(BaseModel):
    label: str
    keyword: str | None = None      # 地點關鍵字(可空)
    match_name: str | None = None   # 指定乘客姓名(可空);keyword 與 match_name 至少一個
    driver_name: str
    time_slot: str = "全天"
    match_field: str = "any"   # passenger | address | any
    fleet: str | None = None
    active: bool = True
    note: str | None = None
    # 既定區塊維護參數
    pickup_address: str | None = None
    dropoff_address: str | None = None
    plate: str | None = None
    start_time: str | None = None      # "HH:MM"
    occupancy_min: int | None = None   # 整趟佔用時間(分);空則用 settings 估算
    pax: int = 1
    vehicle_type: str = "normal"       # normal | welfare
    wheelchair: int = 0
    allow_pool: bool = False           # 預設不可併(各釘各車)


class FixedRouteCreate(FixedRouteBase):
    pass


class FixedRouteUpdate(FixedRouteBase):
    pass


class FixedRouteOut(FixedRouteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: datetime | None = None
