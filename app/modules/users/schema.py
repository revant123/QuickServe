import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.users.model import Role


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # ADMIN is deliberately not in this list: if anyone could sign up as an admin,
    # the role would mean nothing. Admins are created by an existing admin or a script.
    role: Literal["CUSTOMER", "RESTAURANT_OWNER", "RIDER"] = "CUSTOMER"


class UserOut(BaseModel):
    # No password_hash here. The response schema decides what leaves the server.
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    role: Role
