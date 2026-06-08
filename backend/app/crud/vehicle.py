from app.crud.base import CRUDBase
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleUpdate

vehicle = CRUDBase[Vehicle, VehicleCreate, VehicleUpdate](Vehicle)
