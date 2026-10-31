import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from ..core.config import get_config
from ..core.db import get_session
from ..core.security import ALGORITHM
from ..models.user import TokenPayload, User

reusable_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(session: Session = Depends(get_session), token: str = Depends(reusable_oauth2)) -> User:
    config = get_config()
    try:
        payload = jwt.decode(
            token, config.security.secret_key, algorithms=[ALGORITHM], options={"require": ["sub", "exp"]}
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError) as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        ) from err
    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("ver", 0) != user.token_version:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Inactive user")
    return user
