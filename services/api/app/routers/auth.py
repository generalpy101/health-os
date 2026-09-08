from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import LoginIn, SignupIn, UserOut
from ..security import create_session, delete_session
from ..services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.cookie_name, token, max_age=s.session_ttl_days * 86400,
        httponly=True, samesite="lax", secure=s.cookie_secure, path="/",
    )


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(data: SignupIn, response: Response, db: AsyncSession = Depends(get_db)):
    user = await auth_service.signup(db, data)
    _set_cookie(response, await create_session(db, user))
    return user


@router.post("/login", response_model=UserOut)
async def login(data: LoginIn, response: Response, db: AsyncSession = Depends(get_db)):
    user = await auth_service.authenticate(db, data.email, data.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    _set_cookie(response, await create_session(db, user))
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, db: AsyncSession = Depends(get_db),
                 user: User = Depends(current_user)):
    # token cleared client-side; session row cleanup is best-effort via cookie value
    response.delete_cookie(get_settings().cookie_name, path="/")
    return None


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user
