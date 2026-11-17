import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, Timestamps, UUIDPrimaryKey

if TYPE_CHECKING:
    from app.modules.menu.model import MenuItem


class Restaurant(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "restaurants"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str] = mapped_column(String(500))
    is_open: Mapped[bool] = mapped_column(default=True)
    # Charged once per order by the restaurant, like Swiggy/Zomato packaging charges.
    packaging_charge: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))

    # One restaurant -> many menu items. lazy="raise" makes an accidental lazy load
    # an error instead of a silent extra query (the N+1 trap). We must ask for the
    # items explicitly with selectinload()/joinedload().
    menu_items: Mapped[list["MenuItem"]] = relationship(back_populates="restaurant", lazy="raise")
