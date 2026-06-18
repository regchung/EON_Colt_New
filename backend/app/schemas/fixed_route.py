from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FixedRouteBase(BaseModel):
    label: str
    keyword: str
    driver_name: str
    time_slot: str = "全天"
    match_field: str = "any"   # passenger | address | any
    fleet: str | None = None
    active: bool = True
    note: str | None = None


class FixedRouteCreate(FixedRouteBase):
    pass


class FixedRouteUpdate(FixedRouteBase):
    pass


class FixedRouteOut(FixedRouteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: datetime | None = None
