#!/usr/bin/env bash
# OSRM 前處理:下載台灣 OSM 圖資並建索引(MLD pipeline)。
# 一次性執行;完成後 docker-compose 的 osrm 服務即可啟動 osrm-routed。
#
# 用法:  ./osrm/prepare.sh        (或 make osrm-prepare)
set -euo pipefail
cd "$(dirname "$0")"

DATA_DIR="$PWD/data"
PBF_URL="${PBF_URL:-https://download.geofabrik.de/asia/taiwan-latest.osm.pbf}"
PBF="taiwan-latest.osm.pbf"
PROFILE="/opt/car.lua"
IMG="ghcr.io/project-osrm/osrm-backend:latest"

mkdir -p "$DATA_DIR"

if [ ! -f "$DATA_DIR/$PBF" ]; then
  echo "==> 下載台灣 OSM 圖資($PBF_URL)..."
  curl -L --fail -o "$DATA_DIR/$PBF" "$PBF_URL"
else
  echo "==> 已存在 $PBF,略過下載。"
fi

run() { docker run --rm -t -v "$DATA_DIR:/data" "$IMG" "$@"; }

echo "==> osrm-extract(car profile)..."
run osrm-extract -p "$PROFILE" "/data/$PBF"

BASE="taiwan-latest"
echo "==> osrm-partition..."
run osrm-partition "/data/$BASE.osrm"

echo "==> osrm-customize..."
run osrm-customize "/data/$BASE.osrm"

echo "==> 完成!現在可執行:docker compose up -d osrm"
