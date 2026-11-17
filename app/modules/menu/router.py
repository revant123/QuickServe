"""HTTP layer for menus. Routers only translate HTTP <-> service calls; no business rules here."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.menu import analytics, repository, service
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

router = APIRouter(tags=["menu"])


@router.post("/restaurants/{restaurant_id}/menu", response_model=MenuItemOut, status_code=201)
def add_menu_item(restaurant_id: uuid.UUID, body: MenuItemCreate, db: Session = Depends(get_db)):
    return service.create_menu_item(db, restaurant_id, body)


@router.get("/restaurants/{restaurant_id}/menu", response_model=list[MenuItemPublic])
def customer_menu(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    return service.customer_menu(db, restaurant_id)


@router.get("/restaurants/{restaurant_id}/menu/manage", response_model=list[MenuItemOut])
def owner_menu(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    """The restaurant's view, with raw stock and consumed counters."""
    return repository.list_menu(db, restaurant_id)


@router.post("/menu/{menu_item_id}/restock", response_model=RestockResult)
def restock(menu_item_id: uuid.UUID, body: RestockRequest, db: Session = Depends(get_db)):
    closed, item = service.restock(db, menu_item_id, body.quantity, body.carry_over_leftover)
    return RestockResult(closed_cycle=CycleOut.model_validate(closed), item=MenuItemOut.model_validate(item))


@router.patch("/menu/{menu_item_id}/availability", response_model=MenuItemOut)
def set_availability(menu_item_id: uuid.UUID, body: AvailabilityUpdate, db: Session = Depends(get_db)):
    return service.set_availability(db, menu_item_id, body)


@router.get("/menu/{menu_item_id}/cycles", response_model=list[CycleOut])
def cycle_history(menu_item_id: uuid.UUID, db: Session = Depends(get_db)):
    return repository.list_cycles(db, menu_item_id)


@router.get("/menu/{menu_item_id}/restock-suggestion", response_model=RestockSuggestion)
def restock_suggestion(menu_item_id: uuid.UUID, db: Session = Depends(get_db)):
    return service.restock_suggestion(db, menu_item_id)


@router.get("/restaurants/{restaurant_id}/best-sellers", response_model=list[BestSellerRow])
def best_sellers(restaurant_id: uuid.UUID, days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)):
    since = repository.db_now(db) - timedelta(days=days)
    return analytics.best_sellers_orm(db, restaurant_id, since)
