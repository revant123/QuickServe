from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.modules.users import service
from app.modules.users.schema import UserCreate, UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserOut, status_code=201)
def register(body: UserCreate, db: Session = Depends(get_db)):
    """Registration. Login and JWT auth come in the next task."""
    return service.register(db, body)
