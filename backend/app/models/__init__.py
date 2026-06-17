from app.models.vehicle import Vehicle
from app.models.driver import Driver
from app.models.order import Order
from app.models.address import AddressPoint, AddressAlias
from app.models.route import RouteStop
from app.models.user import User
from app.models.dispatch_history import DispatchHistory
from app.models.dispatch_comparison import DispatchComparison

__all__ = [
    "Vehicle", "Driver", "Order", "AddressPoint", "AddressAlias",
    "RouteStop", "User", "DispatchHistory", "DispatchComparison",
]
