"""使用者管理(需管理員)。"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.security import hash_password
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])

RoleType = Literal["admin", "dispatcher", "driver"]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: str
    vehicle_id: int | None
    created_at: datetime


class UserCreate(BaseModel):
    username: str
    password: str
    role: RoleType = "admin"
    vehicle_id: int | None = None


class PasswordUpdate(BaseModel):
    password: str


class RoleUpdate(BaseModel):
    role: RoleType


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.id)).all())


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    if not payload.username.strip() or len(payload.password) < 4:
        raise HTTPException(status_code=400, detail="帳號不可空白,密碼至少 4 碼")
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=409, detail="帳號已存在")
    user = User(
        username=payload.username.strip(),
        hashed_password=hash_password(payload.password),
        role=payload.role,
        vehicle_id=payload.vehicle_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{id}/password", response_model=UserOut)
def reset_password(id: int, payload: PasswordUpdate, db: Session = Depends(get_db)):
    if len(payload.password) < 4:
        raise HTTPException(status_code=400, detail="密碼至少 4 碼")
    user = db.get(User, id)
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    user.hashed_password = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{id}/role", response_model=UserOut)
def update_role(id: int, payload: RoleUpdate, db: Session = Depends(get_db)):
    user = db.get(User, id)
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{id}", status_code=204)
def delete_user(id: int, db: Session = Depends(get_db)):
    user = db.get(User, id)
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    if db.scalar(select(func.count()).select_from(User)) <= 1:
        raise HTTPException(status_code=400, detail="不可刪除最後一個使用者")
    db.delete(user)
    db.commit()
