from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.users import service
from app.modules.users.model import User
from app.modules.users.schema import UserCreate, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserOut, status_code=201)
def register(body: UserCreate, db: Session = Depends(get_db)):
    """Sign up as a customer, restaurant owner or rider. Then log in at /auth/login."""
    return service.register(db, body)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """Who am I? Handy for checking that your token works."""
    return user
