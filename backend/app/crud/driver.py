from app.crud.base import CRUDBase
from app.models.driver import Driver
from app.schemas.driver import DriverCreate, DriverUpdate

driver = CRUDBase[Driver, DriverCreate, DriverUpdate](Driver)
