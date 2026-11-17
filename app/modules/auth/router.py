from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.modules.auth import service

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Log in with your email (in the `username` field) and password.

    This uses the standard OAuth2 password form, which is what makes the
    "Authorize" button in Swagger UI work. Send the token you get back as the
    header `Authorization: Bearer <access_token>` on later requests.
    """
    token = service.login(db, form.username, form.password)
    return TokenOut(access_token=token, expires_in_minutes=get_settings().access_token_expire_minutes)
