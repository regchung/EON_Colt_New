"""距離矩陣抽象層:依 MATRIX_PROVIDER 切換 osrm / map8 / haversine。

回傳一律為 {"durations": [[秒]], "distances": [[公尺]] | None, "provider": str}。
排班程式只依賴這個介面,矩陣來源可隨時抽換。
"""
from __future__ import annotations

import math

from app.core.config import settings
from app.services import map8, osrm


def _haversine_matrix(points: list[tuple[float, float]], kmph: float = 25.0) -> dict:
    """直線距離備援:以平均時速估算行車時間(無路網,僅供 OSRM 不可用時跑通)。"""
    n = len(points)
    durations = [[0.0] * n for _ in range(n)]
    distances = [[0.0] * n for _ in range(n)]
    mps = kmph * 1000 / 3600
    for i in range(n):
        lng1, lat1 = points[i]
        for j in range(n):
            if i == j:
                continue
            lng2, lat2 = points[j]
            r = 6371000
            p1, p2 = math.radians(lat1), math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlmb = math.radians(lng2 - lng1)
            a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
            d = 2 * r * math.asin(math.sqrt(a))
            distances[i][j] = round(d, 1)
            durations[i][j] = round(d / mps, 1)
    return {"durations": durations, "distances": distances, "provider": "haversine"}


def build_matrix(points: list[tuple[float, float]]) -> dict:
    provider = settings.MATRIX_PROVIDER
    if provider == "osrm":
        m = osrm.distance_matrix(points)
        return {**m, "provider": "osrm"}
    if provider == "map8":
        m = map8.distance_matrix(points)
        return {**m, "provider": "map8"}
    return _haversine_matrix(points)
