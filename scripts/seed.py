"""Load demo data so you can click around in Swagger UI (/docs).

Run:  python -m scripts.seed
Safe to run twice: it skips the demo data if it already exists.
"""

from decimal import Decimal

from sqlalchemy import select

import app.database.models  # noqa: F401
from app.core.security import hash_password
from app.database.session import SessionLocal
from app.modules.coupons.model import Coupon, CouponFunder
from app.modules.menu.schema import MenuItemCreate
from app.modules.menu.service import create_menu_item
from app.modules.pricing.calculator import CouponKind
from app.modules.restaurants.model import Restaurant
from app.modules.users.model import Role, User

# Demo logins for local development only. Never reuse these passwords anywhere real.
DEMO_USERS = {
    "customer@quickserve.dev": ("Demo Customer", Role.CUSTOMER, "customer-pass-123"),
    "owner@quickserve.dev": ("Demo Owner", Role.RESTAURANT_OWNER, "owner-pass-123"),
    "rider@quickserve.dev": ("Demo Rider", Role.RIDER, "rider-pass-123"),
    "admin@quickserve.dev": ("Demo Admin", Role.ADMIN, "admin-pass-123"),
}

# Where the demo restaurants are (Phase 11): delivery fees depend on distance.
LOCATIONS = {
    "Pal Dhaba": (Decimal("30.719300"), Decimal("76.803000")),  # Sector 28
    "Sindhi Sweets": (Decimal("30.739800"), Decimal("76.782700")),  # Sector 17
}

# Demo coupons (Phase 11). Try them in POST /api/v1/orders/quote.
DEMO_COUPONS = [
    dict(
        code="WELCOME50",
        description="50% off up to Rs 100 on your first order above Rs 149",
        kind=CouponKind.PERCENT,
        value=Decimal("50"),
        max_discount=Decimal("100"),
        min_order_value=Decimal("149"),
        first_order_only=True,
        funded_by=CouponFunder.PLATFORM,
    ),
    dict(
        code="FLAT75",
        description="Rs 75 off orders above Rs 399, twice per customer, first 1000 uses",
        kind=CouponKind.FLAT,
        value=Decimal("75"),
        min_order_value=Decimal("399"),
        max_uses_per_user=2,
        max_uses_total=1000,
        funded_by=CouponFunder.PLATFORM,
    ),
]

MENUS = {
    ("Pal Dhaba", "Sector 28-D, Chandigarh", "15.00"): [
        ("Dal Makhani", "240.00", True, 30),
        ("Butter Chicken", "380.00", False, 25),
        ("Butter Naan", "50.00", True, 120),
        ("Kadhai Paneer", "300.00", True, 20),
    ],
    ("Sindhi Sweets", "Sector 17, Chandigarh", "10.00"): [
        ("Chole Bhature", "180.00", True, 40),
        ("Samosa", "25.00", True, 200),
        ("Rasmalai", "120.00", True, 30),
        ("Masala Chai", "40.00", True, None),  # made to order, not counted
    ],
}


def print_logins() -> None:
    print("\nDemo logins. In Swagger click 'Authorize' and put the email in the 'username' box:")
    for email, (_name, role, password) in DEMO_USERS.items():
        print(f"  {role.value:<17} {email:<26} {password}")


def add_phase11_data(db) -> None:
    """Locations and coupons. Also run for a database seeded before Phase 11."""
    for name, (lat, lng) in LOCATIONS.items():
        r = db.execute(select(Restaurant).where(Restaurant.name == name)).scalar_one_or_none()
        if r is not None and r.latitude is None:
            r.latitude, r.longitude = lat, lng
            print(f"Set the location of {name}")
    for fields in DEMO_COUPONS:
        if db.execute(select(Coupon).where(Coupon.code == fields["code"])).scalar_one_or_none() is None:
            db.add(Coupon(**fields))
            print(f"Added demo coupon {fields['code']}")
    db.commit()


def main() -> None:
    with SessionLocal() as db:
        if db.execute(select(User).where(User.email == "owner@quickserve.dev")).scalar_one_or_none():
            # Data from an older seed: add any demo accounts that didn't exist back then
            # (the rider and admin arrived with Phase 3).
            for email, (name, role, password) in DEMO_USERS.items():
                if db.execute(select(User).where(User.email == email)).scalar_one_or_none() is None:
                    db.add(User(name=name, email=email, role=role, password_hash=hash_password(password)))
                    print(f"Added missing demo account: {email}")
            db.commit()
            add_phase11_data(db)
            print("Demo restaurants already loaded.")
            print_logins()
            return

        users: dict[Role, User] = {}
        # Rider and admin can't sign up through the API, so the script creates them directly.
        for email, (name, role, password) in DEMO_USERS.items():
            users[role] = User(name=name, email=email, role=role, password_hash=hash_password(password))
            db.add(users[role])
        db.commit()
        owner = users[Role.RESTAURANT_OWNER]

        for (name, address, packaging), items in MENUS.items():
            lat, lng = LOCATIONS[name]
            r = Restaurant(
                owner_id=owner.id,
                name=name,
                address=address,
                packaging_charge=Decimal(packaging),
                latitude=lat,
                longitude=lng,
            )
            db.add(r)
            db.commit()
            print(f"\n{name:<14} restaurant_id {r.id}")
            for item_name, price, veg, stock in items:
                data = MenuItemCreate(
                    name=item_name, price=Decimal(price), is_veg=veg, track_stock=stock is not None, stock=stock
                )
                item = create_menu_item(db, r.id, data, owner)
                print(f"  {item_name:<16} menu_item_id {item.id}  stock={stock}")
        add_phase11_data(db)
        print_logins()


if __name__ == "__main__":
    main()
