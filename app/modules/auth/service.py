from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import Unauthorized
from app.core.security import create_access_token, verify_password
from app.modules.users.model import User

# One message for "no such email" and "wrong password". Different messages would
# let anyone discover which emails have accounts (account enumeration).
BAD_CREDENTIALS = "Incorrect email or password"


def login(db: Session, email: str, password: str) -> str:
    user = db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
    # verify_password runs a full hash check even when user is None, so both
    # failure cases take the same time.
    if not verify_password(password, user.password_hash if user else None) or user is None:
        raise Unauthorized(BAD_CREDENTIALS)
    return create_access_token(user.id, user.role.value)
