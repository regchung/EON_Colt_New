from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.deps import get_current_user
from app.api.routes import (
    addresses,
    auth,
    config,
    dispatch,
    driver,
    drivers,
    health,
    history,
    orders,
    reports,
    users,
    vehicles,
)
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動時:若無任何使用者,建立預設管理員帳號
    db = SessionLocal()
    try:
        if not db.scalar(select(User)):
            db.add(User(
                username=settings.ADMIN_USERNAME,
                hashed_password=hash_password(settings.ADMIN_PASSWORD),
                role="admin",
            ))
            db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 公開路由(免登入)
app.include_router(health.router, prefix=settings.API_PREFIX)
app.include_router(config.router, prefix=settings.API_PREFIX)
app.include_router(auth.router, prefix=settings.API_PREFIX)

# 受保護路由(需 JWT)
protected = [Depends(get_current_user)]
app.include_router(vehicles.router, prefix=settings.API_PREFIX, dependencies=protected)
app.include_router(drivers.router, prefix=settings.API_PREFIX, dependencies=protected)
app.include_router(orders.router, prefix=settings.API_PREFIX, dependencies=protected)
app.include_router(dispatch.router, prefix=settings.API_PREFIX, dependencies=protected)
app.include_router(addresses.router, prefix=settings.API_PREFIX, dependencies=protected)
app.include_router(users.router, prefix=settings.API_PREFIX)
app.include_router(reports.router, prefix=settings.API_PREFIX)
app.include_router(driver.router, prefix=settings.API_PREFIX, dependencies=protected)
app.include_router(history.router, prefix=settings.API_PREFIX, dependencies=protected)
