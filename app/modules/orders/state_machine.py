"""Which status changes are allowed, and what each one does to stock.

Keeping this as data (a dict) instead of scattered if-statements means the
whole lifecycle can be read, tested and drawn from one place.
"""

from app.modules.orders.model import OrderStatus as S

ALLOWED = {
    S.PLACED: {S.PAID, S.PAYMENT_FAILED, S.CANCELLED},
    S.PAID: {S.ACCEPTED, S.REJECTED, S.CANCELLED},
    S.ACCEPTED: {S.PREPARING, S.CANCELLED},
    S.PREPARING: {S.READY, S.CANCELLED},
    S.READY: {S.OUT_FOR_DELIVERY},
    S.OUT_FOR_DELIVERY: {S.DELIVERED},
    S.DELIVERED: set(),
    S.CANCELLED: set(),
    S.REJECTED: set(),
    S.PAYMENT_FAILED: set(),
}

TERMINAL = {s for s, nxt in ALLOWED.items() if not nxt}
FAILED_ENDINGS = {S.CANCELLED, S.REJECTED, S.PAYMENT_FAILED}

# Before cooking starts, a failed order gives its units back to stock.
# After cooking starts, the food exists: it can't be resold, so it is counted as waste.
RELEASE_STOCK_FROM = {S.PLACED, S.PAID, S.ACCEPTED}
WASTE_STOCK_FROM = {S.PREPARING}

# Who may perform which change. Auth comes later; for now the caller passes an actor.
ACTORS = {
    S.PAID: {"system"},
    S.PAYMENT_FAILED: {"system"},
    S.ACCEPTED: {"restaurant"},
    S.REJECTED: {"restaurant", "system"},
    S.PREPARING: {"restaurant"},
    S.READY: {"restaurant"},
    S.OUT_FOR_DELIVERY: {"rider"},
    S.DELIVERED: {"rider"},
    S.CANCELLED: {"customer", "support"},
}
# Customers can cancel only before the restaurant accepts. After that, only support can.
CUSTOMER_CANCELLABLE = {S.PLACED, S.PAID}


def can_transition(current: S, target: S) -> bool:
    return target in ALLOWED[current]
