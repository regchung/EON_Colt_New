#!/usr/bin/env bash
# 在「來源機」執行:把專案 + 展示資料打包成可攜帶 zip,排除大檔/敏感物。
# 產出 demo/dr_fish-demo-bundle.zip,拷到展示機解壓後跑 demo/start-demo.sh 即可。
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="demo/dr_fish-demo-bundle.zip"

if [ ! -f demo/dr_fish.dump ]; then
  echo "⚠️ 找不到 demo/dr_fish.dump,先跑 demo/make-demo-data.sh 產生資料。"
  exit 1
fi

echo "==> 打包(排除 .git / node_modules / osrm 大檔 / 快取)→ $OUT"
rm -f "$OUT"
zip -r -q "$OUT" . \
  -x '*.git/*' \
  -x '*/node_modules/*' \
  -x 'osrm/data/*' \
  -x 'osrm/prepare.log' \
  -x '*/__pycache__/*' \
  -x '*.pyc' \
  -x '*/dist/*' \
  -x '*/.venv/*' \
  -x 'demo/dr_fish-demo-bundle.zip'

SIZE=$(du -h "$OUT" | cut -f1)
echo "==> 完成:$OUT($SIZE)"
echo "    內含 demo/dr_fish.dump(真實 PII)→ 用加密媒介傳輸,展示後請刪除。"
echo "    展示機步驟:解壓 → cd 專案 → bash demo/start-demo.sh"
