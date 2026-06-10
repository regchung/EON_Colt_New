"""共用相依:目前登入使用者(JWT Bearer)與角色守衛。"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(status_code=401, detail="未提供憑證")
    payload = decode_token(cred.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="憑證無效或已過期")
    user = db.scalar(select(User).where(User.username == payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="使用者不存在")
    return user


def require_admin(current: User = Depends(get_current_user)) -> User:
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理員權限")
    return current


def require_dispatcher(current: User = Depends(get_current_user)) -> User:
    if current.role not in ("admin", "dispatcher"):
        raise HTTPException(status_code=403, detail="需要派遣員以上權限")
    return current


def require_driver(current: User = Depends(get_current_user)) -> User:
    """司機/派遣員/管理員皆可通過。"""
    if current.role not in ("admin", "dispatcher", "driver"):
        raise HTTPException(status_code=403, detail="需要登入")
    return current
