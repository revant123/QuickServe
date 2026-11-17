"""FastAPI dependencies that answer "who is calling, and may they?".

Add `user: User = Depends(get_current_user)` to an endpoint and FastAPI will:
  1. read the "Authorization: Bearer <token>" header,
  2. reject the request with 401 if it's missing, invalid or expired,
  3. load that user from the database and hand it to the endpoint.

Role and ownership rules (who may restock THIS restaurant's dish) live in the
service layer, next to the business logic they protect.
"""

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.exceptions import Forbidden, Unauthorized
from app.core.security import TokenClaims, decode_access_token
from app.database.session import get_db
from app.modules.auth import revocation
from app.modules.users.model import Role, User

# tokenUrl tells Swagger UI where its "Authorize" button should send email + password.
# auto_error=False: we raise our own 401 so every auth error has the same shape.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_token_claims(token: str | None = Depends(oauth2_scheme)) -> TokenClaims:
    if not token:
        raise Unauthorized("Not logged in")
    claims = decode_access_token(token)
    if revocation.is_revoked(claims):
        raise Unauthorized("This token was logged out, please log in again")
    return claims


def get_current_user(claims: TokenClaims = Depends(get_token_claims), db: Session = Depends(get_db)) -> User:
    user_id = claims.user_id
    # Look the user up on every request instead of trusting the role inside the
    # token. If an admin changes someone's role or deletes the account, it takes
    # effect immediately, not when the token expires.
    user = db.get(User, user_id)
    if user is None:
        raise Unauthorized("Account no longer exists")
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    """Usage: user: User = Depends(require_roles(Role.ADMIN))"""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            allowed = ", ".join(r.value for r in roles)
            raise Forbidden(f"This action needs one of these roles: {allowed}")
        return user

    return checker
