from fastapi import APIRouter

from app.modules.menu.router import router as menu_router
from app.modules.orders.router import router as orders_router
from app.modules.payments.router import router as payments_router
from app.modules.restaurants.router import router as restaurants_router
from app.modules.users.router import router as users_router

api_router = APIRouter(prefix="/api/v1")
for r in (users_router, restaurants_router, menu_router, orders_router, payments_router):
    api_router.include_router(r)
