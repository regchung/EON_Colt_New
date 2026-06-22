from datetime import time

from pydantic import BaseModel, ConfigDict


class VehicleBase(BaseModel):
    plate: str | None = None
    type: str = "normal"  # 'welfare' | 'normal'
    seats: int = 4
    shift_start: time | None = None
    shift_end: time | None = None
    depot_lng: float | None = None
    depot_lat: float | None = None
    start_lng: float | None = None
    start_lat: float | None = None
    end_lng: float | None = None
    end_lat: float | None = None
    home_fleet: str | None = None
    active: bool = True
    suspended: bool = False


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(VehicleBase):
    pass


class VehicleOut(VehicleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
