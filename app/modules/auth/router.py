from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import TokenClaims
from app.database.session import get_db
from app.modules.auth import revocation, service
from app.modules.auth.dependencies import get_token_claims

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


@router.post("/login", response_model=TokenOut)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Log in with your email (in the `username` field) and password.

    This uses the standard OAuth2 password form, which is what makes the
    "Authorize" button in Swagger UI work. Send the token you get back as the
    header `Authorization: Bearer <access_token>` on later requests.
    After 5 wrong passwords for one email (20 from one IP) in 15 minutes,
    login answers 429 Too Many Requests until the window ends.
    """
    client_ip = request.client.host if request.client else "unknown"
    token = service.login(db, form.username, form.password, client_ip)
    return TokenOut(access_token=token, expires_in_minutes=get_settings().access_token_expire_minutes)


@router.post("/logout", status_code=204, response_class=Response)
def logout(claims: TokenClaims = Depends(get_token_claims)):
    """Invalidate the token you're using right now. Other devices stay logged in."""
    revocation.revoke(claims)
    return Response(status_code=204)
