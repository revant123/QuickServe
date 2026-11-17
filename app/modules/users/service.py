from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict
from app.core.security import hash_password
from app.modules.users.model import Role, User
from app.modules.users.schema import UserCreate


def register(db: Session, data: UserCreate) -> User:
    user = User(
        name=data.name,
        email=data.email.lower(),
        role=Role(data.role),
        password_hash=hash_password(data.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # We don't SELECT first to check "does this email exist?": two sign-ups
        # could both pass that check. The UNIQUE index decides, atomically.
        db.rollback()
        raise Conflict("Email already registered") from None
    return user
