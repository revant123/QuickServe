"""Domain errors.

The service layer raises these. It never raises HTTPException, because the
service layer must not know that HTTP exists: the same service could be called
from a background job, a CLI script or a message consumer. main.py converts
them into HTTP responses in one place.
"""


class DomainError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Unauthorized(DomainError):
    """401: we don't know who you are (no token, bad token, expired token, wrong password)."""

    status_code = 401


class Forbidden(DomainError):
    """403: we know who you are, and you're not allowed to do this."""

    status_code = 403


class TooManyRequests(DomainError):
    """429: slow down. retry_after tells the client how many seconds to wait."""

    status_code = 429

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class ServiceUnavailable(DomainError):
    """503: a dependency we need for this specific action is down."""

    status_code = 503


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class OutOfStock(Conflict):
    """Raised when an item cannot cover the requested quantity."""


class InvalidTransition(Conflict):
    """Raised when an order is moved to a status its current status does not allow."""


class Unprocessable(DomainError):
    """422: the request is well-formed, but we can't do what it asks."""

    status_code = 422


class NotServiceable(Unprocessable):
    """The delivery address is outside the restaurant's delivery area."""


class CouponRejected(Unprocessable):
    """The coupon exists (or not) but can't be used on this order. The message says why."""


class PriceChanged(Conflict):
    """The price moved between the quote the customer saw and the order (surge started,
    a coupon ran out). The customer must see the new price before paying it."""

    def __init__(self, message: str, new_total):
        super().__init__(message)
        self.extra = {"new_grand_total": str(new_total)}
