from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.coupons.router import router as coupons_router
from app.modules.menu.router import router as menu_router
from app.modules.notifications.router import router as notifications_router
from app.modules.orders.router import router as orders_router
from app.modules.payments.router import router as payments_router
from app.modules.pricing.router import router as pricing_router
from app.modules.restaurants.router import router as restaurants_router
from app.modules.users.router import router as users_router

api_router = APIRouter(prefix="/api/v1")
for r in (
    auth_router,
    users_router,
    restaurants_router,
    menu_router,
    orders_router,
    payments_router,
    notifications_router,
    pricing_router,
    coupons_router,
):
    api_router.include_router(r)
