import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.coupons.model import CouponFunder
from app.modules.pricing.calculator import CouponKind


class CouponCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9]{3,30}$", examples=["WELCOME50"])
    description: str = Field(min_length=3, max_length=200)
    kind: CouponKind
    value: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    max_discount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    min_order_value: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    restaurant_id: uuid.UUID | None = None
    first_order_only: bool = False
    max_uses_total: int | None = Field(default=None, ge=1)
    max_uses_per_user: int = Field(default=1, ge=1, le=100)
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def percent_makes_sense(self):
        if self.kind is CouponKind.PERCENT and self.value > 100:
            raise ValueError("a percent coupon can't be more than 100%")
        if self.kind is CouponKind.FLAT and self.max_discount is not None:
            raise ValueError("max_discount is only for percent coupons")
        return self


class CouponOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    description: str
    kind: CouponKind
    value: Decimal
    max_discount: Decimal | None
    min_order_value: Decimal
    restaurant_id: uuid.UUID | None
    funded_by: CouponFunder
    first_order_only: bool
    valid_until: datetime | None
