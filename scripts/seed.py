"""Load demo data so you can click around in Swagger UI (/docs).

Run:  python -m scripts.seed
Safe to run twice: it skips the demo data if it already exists.
"""

from decimal import Decimal

from sqlalchemy import select

import app.database.models  # noqa: F401
from app.core.security import hash_password
from app.database.session import SessionLocal
from app.modules.menu.schema import MenuItemCreate
from app.modules.menu.service import create_menu_item
from app.modules.restaurants.model import Restaurant
from app.modules.users.model import Role, User

# Demo logins for local development only. Never reuse these passwords anywhere real.
DEMO_USERS = {
    "customer@quickserve.dev": ("Demo Customer", Role.CUSTOMER, "customer-pass-123"),
    "owner@quickserve.dev": ("Demo Owner", Role.RESTAURANT_OWNER, "owner-pass-123"),
    "rider@quickserve.dev": ("Demo Rider", Role.RIDER, "rider-pass-123"),
    "admin@quickserve.dev": ("Demo Admin", Role.ADMIN, "admin-pass-123"),
}

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


def main() -> None:
    with SessionLocal() as db:
        if db.execute(select(User).where(User.email == "owner@quickserve.dev")).scalar_one_or_none():
            print("Demo data already loaded.")
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
            r = Restaurant(owner_id=owner.id, name=name, address=address, packaging_charge=Decimal(packaging))
            db.add(r)
            db.commit()
            print(f"\n{name:<14} restaurant_id {r.id}")
            for item_name, price, veg, stock in items:
                data = MenuItemCreate(
                    name=item_name, price=Decimal(price), is_veg=veg, track_stock=stock is not None, stock=stock
                )
                item = create_menu_item(db, r.id, data, owner)
                print(f"  {item_name:<16} menu_item_id {item.id}  stock={stock}")
        print_logins()


if __name__ == "__main__":
    main()
