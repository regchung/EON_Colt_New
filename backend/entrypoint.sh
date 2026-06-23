#!/usr/bin/env bash
set -e

echo "==> 等待資料庫 ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432} ..."
until pg_isready -h "${POSTGRES_HOST:-db}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-eon_colt}" >/dev/null 2>&1; do
  sleep 1
done

echo "==> 套用 migration ..."
alembic upgrade head

echo "==> 啟動 FastAPI ..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
