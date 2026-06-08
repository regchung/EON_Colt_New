from app.crud.base import CRUDBase
from app.models.order import Order
from app.schemas.order import OrderCreate, OrderUpdate

order = CRUDBase[Order, OrderCreate, OrderUpdate](Order)
