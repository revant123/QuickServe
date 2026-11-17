import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import TooManyRequests, Unauthorized
from app.core.logging import log_event
from app.core.metrics import LOGINS
from app.core.security import create_access_token, verify_password
from app.modules.auth import rate_limit
from app.modules.users.model import User

log = logging.getLogger("quickserve.auth")

# One message for "no such email" and "wrong password". Different messages would
# let anyone discover which emails have accounts (account enumeration).
BAD_CREDENTIALS = "Incorrect email or password"


def login(db: Session, email: str, password: str, client_ip: str) -> str:
    email = email.strip().lower()
    try:
        rate_limit.ensure_not_locked(email, client_ip)  # before the password check, never after
    except TooManyRequests:
        LOGINS.labels("blocked").inc()
        raise

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    # verify_password runs a full hash check even when user is None, so both
    # failure cases take the same time.
    if not verify_password(password, user.password_hash if user else None) or user is None:
        rate_limit.record_failure(email, client_ip)
        LOGINS.labels("failed").inc()
        # Never log the password, and don't log the email either: a mistyped
        # password is sometimes typed into the email box.
        log_event(log, logging.INFO, "login failed", ip=client_ip)
        raise Unauthorized(BAD_CREDENTIALS)

    rate_limit.clear_email(email)
    LOGINS.labels("success").inc()
    log_event(log, logging.INFO, "login succeeded", user_id=user.id, role=user.role.value)
    return create_access_token(user.id, user.role.value)
