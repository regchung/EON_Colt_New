"""自架 OSRM 用戶端:查 /table 取得行車時間/距離矩陣(供 VROOM 排班)。

OSRM Table API:
  GET {OSRM_URL}/table/v1/driving/{lon,lat;lon,lat;...}?annotations=duration,distance
回應:{"code":"Ok","durations":[[秒]],"distances":[[公尺]]}
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from app.core.config import settings


class OSRMError(RuntimeError):
    pass


def distance_matrix(points: list[tuple[float, float]], profile: str = "driving") -> dict:
    """points 為 [(lng, lat), ...]。回傳 {"durations": [[秒]], "distances": [[公尺]]}。"""
    if len(points) < 2:
        raise OSRMError("至少需要兩個座標點")

    coords = ";".join(f"{lng},{lat}" for lng, lat in points)
    query = urllib.parse.urlencode({"annotations": "duration,distance"})
    url = f"{settings.OSRM_URL}/table/v1/{profile}/{coords}?{query}"

    req = urllib.request.Request(url, headers={"User-Agent": "EON-COLT/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception as e:  # noqa: BLE001
        raise OSRMError(f"無法連線 OSRM:{e}") from e

    if data.get("code") != "Ok":
        raise OSRMError(f"OSRM 回應錯誤:{data.get('code')} {data.get('message', '')}")

    durations = data.get("durations")
    if durations is None:
        raise OSRMError("OSRM 回應缺少 durations")
    return {"durations": durations, "distances": data.get("distances")}


def route_geometry(points: list[tuple[float, float]], profile: str = "driving") -> dict | None:
    """points 為 [(lng, lat), ...] 的依序停靠點。回傳 {"geometry": GeoJSON LineString,
    "distance": 公尺, "duration": 秒},無法路由時回 None。"""
    if len(points) < 2:
        return None
    coords = ";".join(f"{lng},{lat}" for lng, lat in points)
    query = urllib.parse.urlencode({"overview": "full", "geometries": "geojson"})
    url = f"{settings.OSRM_URL}/route/v1/{profile}/{coords}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "EON-COLT/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception as e:  # noqa: BLE001
        raise OSRMError(f"無法連線 OSRM:{e}") from e
    if data.get("code") != "Ok" or not data.get("routes"):
        return None
    r = data["routes"][0]
    return {"geometry": r["geometry"], "distance": r["distance"], "duration": r["duration"]}


def health() -> bool:
    """簡單探活:用台北車站附近兩點查一次小矩陣。"""
    try:
        m = distance_matrix([(121.5174, 25.0478), (121.5636, 25.0338)])
        return bool(m["durations"])
    except Exception:  # noqa: BLE001
        return False
