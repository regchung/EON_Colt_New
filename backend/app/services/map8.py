"""圖霸 Map8 API 低階用戶端。

提供:
- geocode_address(address): 地址 → (lng, lat, precision, formatted)
- distance_matrix(points): 多點 → 行車時間/距離矩陣(供 VROOM 排班)

認證:query 帶 key=<MAP8_API_KEY>。

注意:回應欄位採防禦式解析(圖霸宣稱與 Google/OSRM 相容),
取得實際金鑰做 live 呼叫後會再校正。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from app.core.config import settings


class Map8Error(RuntimeError):
    pass


def _get_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": settings.GEOCODER_USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _require_key() -> str:
    if not settings.MAP8_API_KEY:
        raise Map8Error("未設定 MAP8_API_KEY")
    return settings.MAP8_API_KEY


# --- 地理編碼 ---------------------------------------------------------------

def geocode_address(address: str) -> dict | None:
    """回傳 {lng, lat, precision, formatted} 或 None(查無)。"""
    key = _require_key()
    params = urllib.parse.urlencode({"key": key, "address": address})
    url = f"{settings.MAP8_BASE_URL}/v2/place/geocode/json?{params}"
    data = _get_json(url)
    return _parse_geocode(data)


def _parse_geocode(data) -> dict | None:
    """防禦式解析:支援 Google 相容格式與幾種常見變體。"""
    # Google 相容:{"status":"OK","results":[{"geometry":{"location":{"lat","lng"}}}]}
    results = None
    if isinstance(data, dict):
        if data.get("status") not in (None, "OK") and not data.get("results"):
            return None
        results = data.get("results") or data.get("data")
    elif isinstance(data, list):
        results = data
    if not results:
        return None

    first = results[0]
    lat = lng = None
    geom = first.get("geometry") if isinstance(first, dict) else None
    if geom and isinstance(geom.get("location"), dict):
        loc = geom["location"]
        lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None:
        lat = first.get("lat") or first.get("latitude")
        lng = first.get("lng") or first.get("lon") or first.get("longitude")
    if lat is None or lng is None:
        return None

    return {
        "lng": float(lng),
        "lat": float(lat),
        "precision": str(first.get("level") or first.get("precision") or "exact"),
        "formatted": first.get("formatted_address") or first.get("address"),
        "city": first.get("city"),
        "town": first.get("town"),
    }


# --- 地址正規化 -------------------------------------------------------------

def standardize_address(address: str) -> str | None:
    """呼叫 Map8 /address/standardization 清洗地址，回傳正規化後地址字串（失敗回 None）。"""
    key = _require_key()
    params = urllib.parse.urlencode({"key": key, "address": address})
    url = f"{settings.MAP8_BASE_URL}/v2/place/standardization/json?{params}"
    try:
        data = _get_json(url)
    except Exception:  # noqa: BLE001
        return None

    # 回應格式：{"results":[{"formatted_address":"..."}]} 或 {"standardizedAddress":"..."}
    if isinstance(data, dict):
        results = data.get("results")
        if results and isinstance(results, list):
            return results[0].get("formatted_address") or results[0].get("address")
        return data.get("standardizedAddress") or data.get("formatted_address")
    return None


# --- 距離矩陣(供排班用)-----------------------------------------------------

def distance_matrix(points: list[tuple[float, float]], transport: str = "car") -> dict:
    """points 為 [(lng, lat), ...]。回傳 {"durations": [[秒]], "distances": [[公尺]]}。"""
    key = _require_key()
    coords = ";".join(f"{lng},{lat}" for lng, lat in points)
    params = urllib.parse.urlencode({"key": key, "annotations": "duration,distance"})
    url = f"{settings.MAP8_BASE_URL}/distancematrix/{transport}/{coords}.json?{params}"
    data = _get_json(url)
    if not isinstance(data, dict):
        raise Map8Error(f"非預期的矩陣回應:{type(data).__name__}")
    if data.get("code") not in (None, "Ok", "OK"):
        raise Map8Error(f"矩陣錯誤:{data.get('code')} {data.get('message','')}")
    durations = data.get("durations")
    distances = data.get("distances")
    if durations is None:
        raise Map8Error("矩陣回應缺少 durations")
    return {"durations": durations, "distances": distances}
