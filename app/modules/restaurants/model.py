import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String, text
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
    # Where the food leaves from (Phase 11). Nullable only for restaurants created
    # before locations existed; orders from those are refused until it's set.
    # NUMERIC(9, 6): six decimals of a degree is about 10 cm, plenty for a doorstep.
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    # How far this kitchen is willing to deliver (road km). The platform's own
    # limit (the last delivery fee slab) applies on top.
    delivery_radius_km: Mapped[Decimal] = mapped_column(
        Numeric(4, 1), default=Decimal("7.0"), server_default=text("7.0")
    )

    # One restaurant -> many menu items. lazy="raise" makes an accidental lazy load
    # an error instead of a silent extra query (the N+1 trap). We must ask for the
    # items explicitly with selectinload()/joinedload().
    menu_items: Mapped[list["MenuItem"]] = relationship(back_populates="restaurant", lazy="raise")
