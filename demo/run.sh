#!/usr/bin/env bash
# EON COLT VROOM demo 執行腳本
# 用法:./run.sh
# 需求:Docker。使用 VROOM 官方 binary 直接吃自帶矩陣的 input(不需 OSRM)。
set -euo pipefail
cd "$(dirname "$0")"

IMG="ghcr.io/vroom-project/vroom-docker:v1.14.0"
IN="matrix-mode.json"
OUT="solution.json"

echo "==> 拉取 VROOM image(首次較久)..."
docker pull "$IMG" >/dev/null

echo "==> 求解中..."
# 覆寫 entrypoint,直接呼叫 vroom binary;-i 讀檔、輸出到 stdout
docker run --rm --entrypoint /usr/local/bin/vroom \
  -v "$PWD":/data "$IMG" \
  -i "/data/$IN" > "$OUT"

echo "==> 完成,結果寫入 $OUT。重點摘要:"
echo
jq -r '
  "未派遣訂單數: \(.summary.unassigned)",
  "總行駛秒數:   \(.summary.duration)",
  "",
  (.routes[] |
    "車輛 \(.vehicle) | 載點數 \(.steps | length) | 行駛 \(.duration)s\n" +
    ( [ .steps[] | "   \(.type)\t loc#\(.location_index // "-")\t 到達 \(.arrival)s\t 車上人數 \(.load[0])" ] | join("\n") )
  )
' "$OUT"
