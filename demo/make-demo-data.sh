#!/usr/bin/env bash
# 在「來源機」(目前有真實資料的開發機)執行,匯出整庫成展示用 dump。
# 產出 demo/eon_colt.dump(含全部 18 張表的 schema + 資料 + alembic_version)。
# ⚠️ 此檔含真實 PII,已 gitignore;勿提交、勿放公開位置,攜帶用加密媒介。
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="demo/eon_colt.dump"
echo "==> 從本機 db 容器匯出整庫 → $OUT"
docker compose exec -T db pg_dump -U eon_colt -d eon_colt \
  --no-owner --no-acl -Fc -f /tmp/eon_colt.dump
docker compose cp db:/tmp/eon_colt.dump "$OUT"
docker compose exec -T db rm -f /tmp/eon_colt.dump || true

SIZE=$(du -h "$OUT" | cut -f1)
echo "==> 完成:$OUT($SIZE)"
echo "    下一步:用 demo/package-demo.sh 打包成可攜帶 zip,或直接把整個專案 + 此 dump 拷到展示機。"
