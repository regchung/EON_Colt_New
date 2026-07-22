"""TDX 道路事件即時告警服務。

每次呼叫 get_alerts() 時從快取（15 分鐘 TTL）或 TDX API 取新北市道路事件，
並提供 near_route() 判斷某趟次路線是否受影響。
"""
from __future__ import annotations

import math
import threading
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

from app.core.config import settings

log = logging.getLogger(__name__)

TW = timezone(timedelta(hours=8))

_CACHE_TTL   = 900      # 15 分鐘
_ALERT_DIST_M = 2_000   # 事件影響半徑（公尺）—— 上下車點 ≤ 此距離視為受影響
_TOKEN_TTL   = 3_300    # 55 分鐘

_lock      = threading.Lock()
_alerts:   list[dict] = []
_alerts_ts = 0.0
_token:    str | None = None
_token_ts  = 0.0


# ── 工具 ─────────────────────────────────────────────────────────────────

def _haversine_m(lng1, lat1, lng2, lat2) -> float:
    if None in (lng1, lat1, lng2, lat2):
        return float("inf")
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _get_token() -> str | None:
    global _token, _token_ts
    if not settings.TDX_CLIENT_ID or not settings.TDX_CLIENT_SECRET:
        return None
    with _lock:
        if _token and time.time() - _token_ts < _TOKEN_TTL:
            return _token
    try:
        r = requests.post(
            "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.TDX_CLIENT_ID,
                "client_secret": settings.TDX_CLIENT_SECRET,
            },
            timeout=10,
        )
        r.raise_for_status()
        t = r.json()["access_token"]
        with _lock:
            _token, _token_ts = t, time.time()
        return t
    except Exception as e:
        log.warning(f"TDX token error: {e}")
        return None


def _parse_coord(obj: Any) -> tuple[float, float] | None:
    """從各種 TDX 座標格式解析 (lng, lat)。"""
    if not obj:
        return None
    # {"PositionLon": ..., "PositionLat": ...}
    if isinstance(obj, dict):
        lon = obj.get("PositionLon") or obj.get("Longitude") or obj.get("lon")
        lat = obj.get("PositionLat") or obj.get("Latitude") or obj.get("lat")
        if lon is not None and lat is not None:
            try:
                return float(lon), float(lat)
            except (TypeError, ValueError):
                pass
        # GeoJSON {"type":"Point","coordinates":[lng,lat]}
        if obj.get("type") == "Point":
            c = obj.get("coordinates", [])
            if len(c) >= 2:
                return float(c[0]), float(c[1])
    return None


def _fetch_alerts() -> list[dict]:
    """從 TDX 拉取新北市道路事件並正規化成統一格式。"""
    token = _get_token()
    if not token:
        return []
    now_tw = datetime.now(TW)
    try:
        r = requests.get(
            "https://tdx.transportdata.tw/api/basic/v2/Road/Alert/City/NewTaipei"
            "?$format=JSON&$orderby=StartTime%20desc&$top=200",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json()
        items = raw if isinstance(raw, list) else raw.get("Alerts", raw.get("alerts", []))
    except Exception as e:
        log.warning(f"TDX road alert fetch error: {e}")
        return []

    result: list[dict] = []
    for item in items:
        # 解析座標（可能在 Coordinate / Position / AffectedArea）
        coord = (_parse_coord(item.get("Coordinate"))
                 or _parse_coord(item.get("Position"))
                 or _parse_coord(item.get("StartLocation")))

        # 解析時間
        def _parse_dt(s):
            if not s:
                return None
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(s[:19], fmt[:len(fmt.rstrip("z%"))])
                    return dt.replace(tzinfo=TW) if dt.tzinfo is None else dt.astimezone(TW)
                except Exception:
                    pass
            return None

        start = _parse_dt(item.get("StartTime") or item.get("start_time"))
        end   = _parse_dt(item.get("EndTime")   or item.get("end_time"))

        # 只保留今日仍有效的事件
        if end and end < now_tw:
            continue

        result.append({
            "id":          item.get("AlertID") or item.get("IncidentID") or "",
            "type":        item.get("IncidentType") or item.get("AlertType") or "未知",
            "description": item.get("Description") or item.get("Content") or "",
            "road":        item.get("RoadName") or item.get("Road") or "",
            "direction":   item.get("Direction") or "",
            "start_time":  start.strftime("%H:%M") if start else None,
            "end_time":    end.strftime("%H:%M")   if end   else None,
            "lng":         coord[0] if coord else None,
            "lat":         coord[1] if coord else None,
            "severity":    item.get("Severity") or item.get("Level") or "",
        })

    log.info(f"TDX road alerts: {len(result)} active events")
    return result


def get_alerts() -> list[dict]:
    """取當日有效道路事件（帶快取）。無金鑰或 API 失敗時回空清單。"""
    global _alerts, _alerts_ts
    with _lock:
        if time.time() - _alerts_ts < _CACHE_TTL:
            return list(_alerts)
    fresh = _fetch_alerts()
    with _lock:
        _alerts, _alerts_ts = fresh, time.time()
    return fresh


def near_route(
    pickup_lng: float | None,
    pickup_lat: float | None,
    dropoff_lng: float | None,
    dropoff_lat: float | None,
    alerts: list[dict] | None = None,
) -> list[dict]:
    """回傳影響此趟路線的道路事件清單（上下車點任一在事件半徑內）。"""
    if alerts is None:
        alerts = get_alerts()
    matched: list[dict] = []
    for a in alerts:
        alng, alat = a.get("lng"), a.get("lat")
        if alng is None or alat is None:
            continue
        d_pick   = _haversine_m(pickup_lng,  pickup_lat,  alng, alat)
        d_drop   = _haversine_m(dropoff_lng, dropoff_lat, alng, alat)
        if min(d_pick, d_drop) <= _ALERT_DIST_M:
            matched.append(a)
    return matched
