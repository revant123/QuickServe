import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class SurgeFlag(Base):
    """A switch operations can flip without a deploy, such as "it's raining".

    Fee AMOUNTS are settings (reviewed, versioned in Git, changed by deploying).
    Whether it is raining right now is a fact about the world that changes in
    minutes, so it lives in the database, set by an admin. It switches itself
    off at active_until, so a forgotten switch can't overcharge people for days.
    One flag for the whole platform here; a real one has one per city zone.
    """

    __tablename__ = "surge_flags"

    name: Mapped[str] = mapped_column(String(30), primary_key=True)  # "rain"
    active_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
