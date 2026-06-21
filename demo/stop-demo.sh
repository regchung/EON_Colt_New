#!/usr/bin/env bash
# 停止展示版。加 --wipe 連同資料庫 volume 一併清除(下次重新還原乾淨資料)。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${1:-}" = "--wipe" ]; then
  echo "==> 停止並清除資料庫 volume(下次 start 會重新還原)"
  docker compose down -v
else
  echo "==> 停止容器(保留資料)"
  docker compose down
fi

# 還原原本的 .env(若先前有備份)
if [ -f .env.bak ]; then
  mv .env.bak .env
  echo "==> 已還原原有 .env"
fi
echo "==> 已停止。"
