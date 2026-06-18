from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# 連線 session 時區設為台灣:DB(timestamptz)讀回的 datetime 一律帶 +08,
# 讓 API 序列化 / strftime / 前端字串切割顯示一致為台灣時間(計算邏輯多用 astimezone(TW),不受影響)。
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"options": "-c timezone=Asia/Taipei"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
