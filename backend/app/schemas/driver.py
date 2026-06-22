from pydantic import BaseModel, ConfigDict


class DriverBase(BaseModel):
    name: str
    phone: str | None = None
    license_no: str | None = None
    vehicle_id: int | None = None
    active: bool = True
    suspended: bool = False


class DriverCreate(DriverBase):
    pass


class DriverUpdate(DriverBase):
    pass


class DriverOut(DriverBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
