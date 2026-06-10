"""測試前置:確保管理員存在。

API 測試以 TestClient(app) 非 context-manager 方式呼叫,不會觸發 lifespan
(種子管理員),故在此以 fixture 補種子,讓登入測試在乾淨 DB(CI)也能通過。
"""
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User


@pytest.fixture(scope="session", autouse=True)
def seed_admin():
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
