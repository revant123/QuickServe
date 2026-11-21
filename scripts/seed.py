"""Load demo data so you can click around in Swagger UI (/docs).

Run:  python -m scripts.seed
Safe to run twice: it skips the demo data if it already exists.
"""

from decimal import Decimal
from itertools import cycle

from sqlalchemy import select

import app.database.models  # noqa: F401
from app.core.security import hash_password
from app.database.session import SessionLocal
from app.modules.coupons.model import Coupon, CouponFunder
from app.modules.menu.model import MenuItem
from app.modules.menu.schema import MenuItemCreate
from app.modules.menu.service import create_menu_item
from app.modules.orders import dispatch
from app.modules.orders.model import OrderStatus
from app.modules.orders.schema import GeoPoint, OrderCreate, OrderLineIn
from app.modules.orders.service import change_status, place_order
from app.modules.payments.schema import SimulatedOutcome
from app.modules.payments.service import pay
from app.modules.pricing.calculator import CouponKind
from app.modules.restaurants.model import Restaurant
from app.modules.reviews.model import Review
from app.modules.reviews.schema import ReviewCreate
from app.modules.reviews.service import create_review
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


# ---------- Phase 12: discovery ----------
# Cuisines and usual prep time for every demo restaurant (minutes).
PROFILES = {
    "Pal Dhaba": ("North Indian, Punjabi", 25),
    "Sindhi Sweets": ("Sweets, Street Food", 12),
    "Dosa Junction": ("South Indian", 15),
    "Momo Point": ("Tibetan, Chinese", 18),
    "Marwar Rasoi": ("Rajasthani", 25),
    "Kathiyawadi Thaal": ("Gujarati", 20),
    "Seven Sisters Kitchen": ("Northeast, Assamese, Naga", 25),
}
# Two more (fictional) restaurants, so "near me" has something to sort. Momo
# Point is in Mohali: too far for Sector 17 (about 8.6 km by road), so it shows
# up only for customers near it. Try both points in GET /restaurants/near.
NEW_RESTAURANTS = {
    ("Dosa Junction", "Sector 35-C, Chandigarh", "10.00", (Decimal("30.723000"), Decimal("76.759500"))): [
        ("Masala Dosa", "With sambar and coconut chutney", "150.00", True, 60),
        ("Idli Sambar", "Two steamed rice cakes", "90.00", True, 60),
        ("Filter Coffee", "", "60.00", True, None),
    ],
    ("Momo Point", "Phase 7, Mohali", "10.00", (Decimal("30.709000"), Decimal("76.719000"))): [
        ("Veg Steamed Momos", "Eight pieces, with red chutney", "120.00", True, 80),
        ("Chicken Momos", "Eight pieces", "160.00", False, 80),
        ("Thukpa", "Tibetan noodle soup", "180.00", True, 30),
    ],
    # Phase 13: one restaurant for each regional theme in the customer app.
    ("Marwar Rasoi", "Sector 21, Chandigarh", "10.00", (Decimal("30.727000"), Decimal("76.793000"))): [
        ("Dal Baati Churma", "Baked wheat baatis, panchmel dal, sweet churma", "260.00", True, 40),
        ("Gatte ki Sabzi", "Gram-flour dumplings in a yoghurt curry", "220.00", True, 30),
        ("Laal Maas", "Mutton in a fiery red chilli gravy", "420.00", False, 20),
        ("Ker Sangri", "Desert beans and berries, dry-cooked", "240.00", True, None),
    ],
    ("Kathiyawadi Thaal", "Sector 8, Chandigarh", "10.00", (Decimal("30.742000"), Decimal("76.802000"))): [
        ("Gujarati Thali", "Dal, kadhi, two shaak, rotli, rice, farsan, sweet", "320.00", True, 30),
        ("Khaman Dhokla", "Steamed gram-flour cake with green chutney", "120.00", True, 60),
        ("Methi Thepla", "Four fenugreek flatbreads with pickle", "110.00", True, None),
        ("Undhiyu", "Winter vegetables slow-cooked with spices", "240.00", True, 25),
    ],
    ("Seven Sisters Kitchen", "Sector 34, Chandigarh", "10.00", (Decimal("30.723000"), Decimal("76.768000"))): [
        ("Assamese Thali", "Rice, dal, aloo pitika, khar, saag, pickle", "330.00", True, 30),
        ("Masor Tenga", "Light, tangy Assamese fish curry", "360.00", False, 20),
        ("Smoked Pork with Bamboo Shoot", "Naga style, with raja mirchi", "420.00", False, 20),
        ("Veg Momos", "Eight pieces, with tomato chutney", "150.00", True, 80),
    ],
}
# Demo reviews: (stars, comment). Dosa Junction has a single 5-star review: it
# shows as "New", and sorting by rating still puts Pal Dhaba (4.6 from 10
# reviews) above it. That's the Bayesian average at work (see the README).
DEMO_REVIEWS = {
    "Pal Dhaba": [
        (5, "Dal makhani was rich and creamy"),
        (4, "Good naan, arrived warm"),
        (5, ""),
        (4, ""),
        (5, "Butter chicken as it should be"),
        (5, ""),
        (4, "Slightly late, food was great"),
        (5, ""),
        (5, ""),
        (4, ""),
    ],
    "Sindhi Sweets": [(4, "Fresh samosas"), (4, ""), (5, "Best chole bhature around"), (3, "A bit late")],
    "Dosa Junction": [(5, "Crisp dosa")],
    "Momo Point": [(4, "Spicy chutney, nice"), (3, ""), (4, "")],
    "Marwar Rasoi": [(4, "Baatis soaked in ghee, just right"), (5, ""), (4, "")],
    "Kathiyawadi Thaal": [(4, "Soft, spongy dhokla"), (4, "")],
    "Seven Sisters Kitchen": [(5, "Masor tenga like home"), (4, ""), (5, "Bamboo shoot pork was excellent")],
}
REVIEWER_NAMES = ["Aman Gill", "Priya Sharma", "Rohit Verma", "Simran Kaur", "Karan Mehta"]


def reviewers(db) -> list[User]:
    """Demo customers who write the demo reviews, so the main demo customer's
    first order (and WELCOME50) stays unused."""
    found = []
    for i, name in enumerate(REVIEWER_NAMES, start=1):
        email = f"reviewer{i}@quickserve.dev"
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(name=name, email=email, role=Role.CUSTOMER, password_hash=hash_password(f"reviewer-pass-{i}"))
            db.add(user)
            db.commit()
        found.append(user)
    return found


def deliver_and_review(db, restaurant: Restaurant, reviewer: User, owner: User, rider: User, rating, comment):
    """A real order, through the real code: place, pay, cook, deliver, review.
    Demo data made this way can't break rules the API enforces."""
    item = (
        db.execute(select(MenuItem).where(MenuItem.restaurant_id == restaurant.id).order_by(MenuItem.price.desc()))
        .scalars()
        .first()
    )
    here = GeoPoint(lat=float(restaurant.latitude) + 0.004, lng=float(restaurant.longitude))
    order = place_order(
        db,
        OrderCreate(
            restaurant_id=restaurant.id,
            delivery_address="Demo address",
            delivery_location=here,
            items=[OrderLineIn(menu_item_id=item.id, quantity=1)],
        ),
        reviewer,
    )
    pay(db, order.id, f"seed-{order.id}", SimulatedOutcome.success, reviewer)
    for status, actor in [
        (OrderStatus.ACCEPTED, owner),
        (OrderStatus.PREPARING, owner),
        (OrderStatus.READY, owner),
    ]:
        change_status(db, order.id, status, actor)
    # Phase 14: the rider claims it, picks it up, and delivers it with the customer's code.
    dispatch.claim(db, order.id, rider)
    change_status(db, order.id, OrderStatus.OUT_FOR_DELIVERY, rider)
    change_status(db, order.id, OrderStatus.DELIVERED, rider, delivery_code=order.delivery_code)
    create_review(db, order.id, ReviewCreate(rating=rating, comment=comment), reviewer)


def add_phase12_data(db) -> None:
    """Cuisines, two more restaurants, and demo reviews. Safe to run again."""
    owner = db.execute(select(User).where(User.email == "owner@quickserve.dev")).scalar_one()
    rider = db.execute(select(User).where(User.email == "rider@quickserve.dev")).scalar_one()
    for (name, address, packaging, (lat, lng)), items in NEW_RESTAURANTS.items():
        if db.execute(select(Restaurant).where(Restaurant.name == name)).scalar_one_or_none() is None:
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
            for item_name, description, price, veg, stock in items:
                data = MenuItemCreate(
                    name=item_name,
                    description=description,
                    price=Decimal(price),
                    is_veg=veg,
                    track_stock=stock is not None,
                    stock=stock,
                )
                create_menu_item(db, r.id, data, owner)
            print(f"Added demo restaurant {name}")
    for name, (cuisines, prep) in PROFILES.items():
        r = db.execute(select(Restaurant).where(Restaurant.name == name)).scalar_one_or_none()
        if r is not None and not r.cuisines:
            r.cuisines, r.avg_prep_minutes = cuisines, prep
    db.commit()

    people = reviewers(db)
    added = []
    for name, reviews in DEMO_REVIEWS.items():
        r = db.execute(select(Restaurant).where(Restaurant.name == name)).scalar_one()
        # Per restaurant, so restaurants added later (Phase 13) get theirs too.
        if db.execute(select(Review.id).where(Review.restaurant_id == r.id)).first() is not None:
            continue
        # One review per order; a reviewer can have several orders.
        for (rating, comment), reviewer in zip(reviews, cycle(people)):
            deliver_and_review(db, r, reviewer, owner, rider, rating, comment)
        added.append(name)
    if added:
        print("Added demo reviews (through real orders) for " + ", ".join(added))


def print_discovery_examples() -> None:
    print("\nTry discovery (Phase 12) in Swagger or the browser:")
    print("  GET /api/v1/restaurants/near?lat=30.7333&lng=76.7794&sort=rating   (Sector 22, Chandigarh)")
    print("  GET /api/v1/restaurants/near?lat=30.7046&lng=76.7179               (Mohali: Momo Point appears)")
    print("  GET /api/v1/search?q=paner&lat=30.7333&lng=76.7794                 (a typo on purpose)")


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
            add_phase12_data(db)
            print("Demo restaurants already loaded.")
            print_discovery_examples()
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
        add_phase12_data(db)
        print_discovery_examples()
        print_logins()


if __name__ == "__main__":
    main()
