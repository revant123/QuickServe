"""HTTP layer for menus. Routers only translate HTTP <-> service calls; no business rules here.

Browsing a menu is public. Everything else needs a logged-in owner of THAT
restaurant (or an admin); the service layer checks the ownership.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.menu import service
from app.modules.menu.schema import (
    AvailabilityUpdate,
    BestSellerRow,
    CycleOut,
    MenuItemCreate,
    MenuItemOut,
    MenuItemPublic,
    RestockRequest,
    RestockResult,
    RestockSuggestion,
)
from app.modules.users.model import User

router = APIRouter(tags=["menu"])


@router.post("/restaurants/{restaurant_id}/menu", response_model=MenuItemOut, status_code=201)
def add_menu_item(
    restaurant_id: uuid.UUID,
    body: MenuItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.create_menu_item(db, restaurant_id, body, user)


@router.get("/restaurants/{restaurant_id}/menu", response_model=list[MenuItemPublic])
def customer_menu(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    """Public: what a customer sees, no login needed."""
    return service.customer_menu(db, restaurant_id)


@router.get("/restaurants/{restaurant_id}/menu/manage", response_model=list[MenuItemOut])
def owner_menu(restaurant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The owner's view, with raw stock and consumed counters."""
    return service.owner_menu(db, restaurant_id, user)


@router.post("/menu/{menu_item_id}/restock", response_model=RestockResult)
def restock(
    menu_item_id: uuid.UUID, body: RestockRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    closed, item = service.restock(db, menu_item_id, body.quantity, body.carry_over_leftover, user)
    return RestockResult(closed_cycle=CycleOut.model_validate(closed), item=MenuItemOut.model_validate(item))


@router.patch("/menu/{menu_item_id}/availability", response_model=MenuItemOut)
def set_availability(
    menu_item_id: uuid.UUID,
    body: AvailabilityUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.set_availability(db, menu_item_id, body, user)


@router.get("/menu/{menu_item_id}/cycles", response_model=list[CycleOut])
def cycle_history(menu_item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.cycle_history(db, menu_item_id, user)


@router.get("/menu/{menu_item_id}/restock-suggestion", response_model=RestockSuggestion)
def restock_suggestion(menu_item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.restock_suggestion(db, menu_item_id, user)


@router.get("/restaurants/{restaurant_id}/best-sellers", response_model=list[BestSellerRow])
def best_sellers(
    restaurant_id: uuid.UUID,
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.best_sellers(db, restaurant_id, days, user)
