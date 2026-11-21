"""Who hears about what, and in which words.

Modelled on how Zomato and Swiggy behave: the customer hears about every step;
the restaurant hears about an order only once it is PAID (an unpaid order may
never happen), and again if a paid order is cancelled.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    user_id: str
    kind: str
    title: str
    body: str


class UnknownEvent(ValueError):
    """An event type this service doesn't understand (yet). Retried, then dead-lettered."""


def _rupees(amount: str) -> str:
    return f"₹{float(amount):,.0f}"


def messages_for(event_type: str, p: dict) -> list[Message]:
    """Turn one outbox event into the notifications it causes (possibly none)."""
    customer, owner, place = p["customer_id"], p["owner_id"], p["restaurant_name"]
    total = _rupees(p["grand_total"])

    if event_type == "order.placed":
        return [
            Message(customer, "order.placed", "Order placed", f"Pay {total} to confirm your order from {place}."),
        ]
    if event_type == "order.rider_assigned":  # Phase 14
        rider = p["rider_name"].split()[0]
        return [
            Message(
                customer,
                "order.rider_assigned",
                f"{rider} will deliver your order",
                f"{rider} is heading to {place}. Your delivery code is on the order screen.",
            )
        ]
    if event_type != "order.status_changed":
        raise UnknownEvent(f"don't know how to notify about '{event_type}'")

    status, previous = p["status"], p["previous_status"]
    if status == "PAID":
        return [
            Message(customer, "order.paid", "Payment received", f"We've sent your order to {place}."),
            Message(
                owner,
                "order.new_for_restaurant",
                f"New order: {total}, {p['item_count']} item(s)",
                "Accept it within 4 minutes, or it is rejected automatically and refunded.",
            ),
        ]
    customer_only = {
        "ACCEPTED": ("order.accepted", f"{place} accepted your order", "They'll start cooking shortly."),
        "PREPARING": ("order.preparing", "Your food is being prepared", f"{place} has started cooking."),
        "READY": ("order.ready", "Packed and ready", "Waiting for a delivery partner to pick it up."),
        "OUT_FOR_DELIVERY": (
            "order.out_for_delivery",
            "On the way!",
            "Your delivery partner has picked up your order. Share your delivery code only at the door.",
        ),
        "DELIVERED": ("order.delivered", "Delivered. Enjoy your meal!", f"Rate your order from {place}."),
        "PAYMENT_FAILED": (
            "order.payment_failed",
            "Order cancelled: payment not completed",
            "No money was taken. You can place the order again.",
        ),
        "REJECTED": (
            "order.rejected",
            f"{place} couldn't take your order",
            f"Your refund of {total} has been started.",
        ),
    }
    if status in customer_only:
        kind, title, body = customer_only[status]
        return [Message(customer, kind, title, body)]
    if status == "CANCELLED":
        reason = p.get("note") or "No reason given."
        refund = f" Your refund of {total} has been started." if previous != "PLACED" else ""
        msgs = [Message(customer, "order.cancelled", "Order cancelled", f"{reason}{refund}"[:300])]
        if previous != "PLACED":  # the restaurant only ever saw paid orders
            msgs.append(Message(owner, "order.cancelled_for_restaurant", f"Order cancelled: {total}", reason[:300]))
        return msgs
    return []  # a status nobody needs to hear about
