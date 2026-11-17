import enum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, Timestamps, UUIDPrimaryKey


class Role(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    RESTAURANT_OWNER = "RESTAURANT_OWNER"
    ADMIN = "ADMIN"


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(100))
    # unique=True creates a unique index, which also makes login lookups by email fast.
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), default=Role.CUSTOMER)
