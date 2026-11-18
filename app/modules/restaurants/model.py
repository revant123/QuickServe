import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, SmallInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
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

    # --- Discovery (Phase 12) ---
    # Comma-separated, e.g. "North Indian, Punjabi". The API shows it as a list.
    cuisines: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    # Typical minutes from "accepted" to "ready". Real platforms predict this per
    # order with machine learning; a per-restaurant average is the simple start.
    avg_prep_minutes: Mapped[int] = mapped_column(SmallInteger, default=20, server_default=text("20"))
    # Running totals of the 1-5 star reviews. Kept on the restaurant so a list of
    # 50 restaurants doesn't need 50 AVG() queries over the reviews table.
    # Changed only by an atomic UPDATE (see reviews/service.py), and checked by
    # a nightly-style job that recounts them from the reviews themselves.
    rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    rating_sum: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    # One restaurant -> many menu items. lazy="raise" makes an accidental lazy load
    # an error instead of a silent extra query (the N+1 trap). We must ask for the
    # items explicitly with selectinload()/joinedload().
    menu_items: Mapped[list["MenuItem"]] = relationship(back_populates="restaurant", lazy="raise")

    __table_args__ = (
        CheckConstraint("avg_prep_minutes BETWEEN 1 AND 120", name="prep_minutes_sane"),
        # Every rating is 1 to 5 stars, so the sum must lie between count and 5 x count.
        # A bug that double-counts or loses a review breaks this and fails loudly.
        CheckConstraint(
            "rating_count >= 0 AND rating_sum BETWEEN rating_count AND 5 * rating_count",
            name="rating_totals_consistent",
        ),
        # "Restaurants near me" first cuts a rectangle around the customer:
        # latitude BETWEEN a AND b AND longitude BETWEEN c AND d. A B-tree on
        # (latitude, longitude) finds the latitude band without reading the table.
        Index("ix_restaurants_location", "latitude", "longitude"),
        # Trigram indexes (pg_trgm): make ILIKE '%paneer%' and typo matching fast.
        Index("ix_restaurants_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        Index(
            "ix_restaurants_cuisines_trgm",
            "cuisines",
            postgresql_using="gin",
            postgresql_ops={"cuisines": "gin_trgm_ops"},
        ),
    )

    @property
    def cuisine_list(self) -> list[str]:
        return [c.strip() for c in self.cuisines.split(",") if c.strip()]

    @property
    def rating(self) -> Decimal | None:
        """The plain average customers see, or None ("New") until enough people have rated.

        Sorting uses a different number (a Bayesian average, see discovery/ranking.py):
        the average is what people expect to READ, the Bayesian score is what is fair
        to RANK by.
        """
        if self.rating_count < get_settings().rating_min_count:
            return None
        return (Decimal(self.rating_sum) / Decimal(self.rating_count)).quantize(Decimal("0.1"))
