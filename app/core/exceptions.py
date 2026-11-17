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


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class OutOfStock(Conflict):
    """Raised when an item cannot cover the requested quantity."""


class InvalidTransition(Conflict):
    """Raised when an order is moved to a status its current status does not allow."""
