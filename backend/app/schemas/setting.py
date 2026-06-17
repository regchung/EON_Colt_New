from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SettingBase(BaseModel):
    value: str | None = None
    value_type: str = "str"  # str|int|float|bool
    group: str | None = None
    label: str | None = None
    description: str | None = None


class SettingCreate(SettingBase):
    key: str


class SettingUpdate(SettingBase):
    pass


class SettingOut(SettingBase):
    model_config = ConfigDict(from_attributes=True)
    key: str
    updated_at: datetime | None = None
