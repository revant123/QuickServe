"""Import every model so Base.metadata knows about all tables.

Alembic's autogenerate and the test fixtures import this module. If a model is
not imported anywhere, SQLAlchemy never sees it, and autogenerate silently
produces a migration without that table.
"""

from app.modules.menu.model import InventoryCycle, MenuItem  # noqa: F401
from app.modules.orders.model import Order, OrderItem, OrderStatusEvent  # noqa: F401
from app.modules.payments.model import Payment  # noqa: F401
from app.modules.restaurants.model import Restaurant  # noqa: F401
from app.modules.users.model import User  # noqa: F401
