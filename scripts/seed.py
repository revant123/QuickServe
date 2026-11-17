"""Load demo data so you can click around in Swagger UI (/docs).

Run:  python -m scripts.seed
Safe to run twice: it skips the demo data if it already exists.
"""

from decimal import Decimal

from sqlalchemy import select

import app.database.models  # noqa: F401
from app.database.session import SessionLocal
from app.modules.menu.schema import MenuItemCreate
from app.modules.menu.service import create_menu_item
from app.modules.restaurants.model import Restaurant
from app.modules.users.model import Role, User
from app.modules.users.service import password_hash

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


def main() -> None:
    with SessionLocal() as db:
        if db.execute(select(User).where(User.email == "owner@quickserve.dev")).scalar_one_or_none():
            print("Demo data already loaded.")
            return
        owner = User(
            name="Demo Owner",
            email="owner@quickserve.dev",
            role=Role.RESTAURANT_OWNER,
            password_hash=password_hash.hash("owner-pass-123"),
        )
        customer = User(
            name="Demo Customer",
            email="customer@quickserve.dev",
            role=Role.CUSTOMER,
            password_hash=password_hash.hash("customer-pass-123"),
        )
        db.add_all([owner, customer])
        db.commit()

        print(f"customer_id   {customer.id}")
        for (name, address, packaging), items in MENUS.items():
            r = Restaurant(owner_id=owner.id, name=name, address=address, packaging_charge=Decimal(packaging))
            db.add(r)
            db.commit()
            print(f"\n{name:<14} restaurant_id {r.id}")
            for item_name, price, veg, stock in items:
                item = create_menu_item(
                    db,
                    r.id,
                    MenuItemCreate(
                        name=item_name, price=Decimal(price), is_veg=veg, track_stock=stock is not None, stock=stock
                    ),
                )
                print(f"  {item_name:<16} menu_item_id {item.id}  stock={stock}")


if __name__ == "__main__":
    main()
