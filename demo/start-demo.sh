#!/usr/bin/env bash
# 在「展示機」執行:一鍵啟動單機展示版。
#   1) 套用展示環境變數  2) 起 db  3) 還原真實資料(若空庫)
#   4) 起 backend/frontend  5) 重設展示 admin 密碼  6) 印出登入資訊
# 需求:展示機已安裝 Docker Desktop(或 docker + compose)。
set -euo pipefail
cd "$(dirname "$0")/.."

DUMP="demo/dr_fish.dump"

echo "==> [1/6] 套用展示環境變數(demo/env.demo → .env)"
if [ -f .env ] && [ ! -f .env.bak ]; then
  cp .env .env.bak
  echo "    已備份原有 .env → .env.bak"
fi
cp demo/env.demo .env
# 讀取展示 admin 密碼供稍後重設
ADMIN_PASS=$(grep -E '^ADMIN_PASSWORD=' .env | cut -d= -f2-)

echo "==> [2/6] 啟動資料庫並等待就緒"
docker compose up -d db
until docker compose exec -T db pg_isready -U dr_fish -d dr_fish >/dev/null 2>&1; do
  sleep 1
done

echo "==> [3/6] 檢查是否需還原資料"
HAS_ORDERS=$(docker compose exec -T db psql -U dr_fish -d dr_fish -tAc \
  "select to_regclass('public.orders') is not null" 2>/dev/null | tr -d '[:space:]' || echo "f")
if [ "$HAS_ORDERS" = "t" ]; then
  echo "    已存在資料,跳過還原(要重置請先 demo/stop-demo.sh --wipe)"
elif [ -f "$DUMP" ]; then
  echo "    還原 $DUMP …"
  docker compose cp "$DUMP" db:/tmp/dr_fish.dump
  docker compose exec -T db pg_restore --no-owner --no-acl --clean --if-exists \
    -d "postgresql://dr_fish:dr_fish_pw@localhost:5432/dr_fish" /tmp/dr_fish.dump || true
  docker compose exec -T db rm -f /tmp/dr_fish.dump || true
  ROWS=$(docker compose exec -T db psql -U dr_fish -d dr_fish -tAc "select count(*) from orders" 2>/dev/null | tr -d '[:space:]')
  echo "    還原完成:orders=$ROWS"
else
  echo "    ⚠️ 找不到 $DUMP — 將以空庫啟動(backend 會自動建表 + 種子 admin)。"
fi

echo "==> [4/6] 建置並啟動後端 / 前端(首次需數分鐘)"
docker compose up -d --build backend frontend
echo "    等待後端就緒 …"
until curl -sf http://localhost:8000/api/health >/dev/null 2>&1; do sleep 2; done

echo "==> [5/6] 重設展示 admin 密碼"
docker compose exec -T backend python -c "
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.user import User
from app.core.security import hash_password
db = SessionLocal()
u = db.scalar(select(User).where(User.username == 'admin'))
if u:
    u.hashed_password = hash_password('${ADMIN_PASS}')
    db.commit(); print('    admin 密碼已設為展示密碼')
else:
    db.add(User(username='admin', hashed_password=hash_password('${ADMIN_PASS}'), role='admin'))
    db.commit(); print('    已建立 admin')
db.close()
" || echo "    (重設略過)"

echo
echo "============================================================"
echo " 展示版已啟動 ✅"
echo "   前端:http://localhost:8080"
echo "   後端 API 文件:http://localhost:8000/docs"
echo "   登入:admin / ${ADMIN_PASS}"
echo "------------------------------------------------------------"
echo " 建議展示動線:派遣看板(選歷史日)→ 對比報表(↓18.4%/NT$)"
echo "   → 車輛任務口卡 → 一鍵排班。詳見 demo/README-demo.md"
echo "============================================================"
