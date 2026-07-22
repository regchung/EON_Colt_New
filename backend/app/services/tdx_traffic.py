"""TDX 即時路況整合：取新北市 VD 速度資料，產出行政區路況係數，調整 OSRM 矩陣。"""
from __future__ import annotations

import threading
import time
import logging
from typing import Optional

import numpy as np
import requests

from app.core.config import settings

log = logging.getLogger(__name__)

# 行政區代表座標
_DIST_COORDS: dict[str, tuple[float, float]] = {
    "板橋區":(121.4628,25.0136),"三重區":(121.4867,25.0617),"中和區":(121.5030,24.9986),
    "永和區":(121.5198,25.0145),"新莊區":(121.4498,25.0399),"新店區":(121.5415,24.9723),
    "樹林區":(121.4222,24.9939),"鶯歌區":(121.3475,24.9555),"三峽區":(121.3720,24.9365),
    "淡水區":(121.4512,25.1695),"汐止區":(121.6557,25.0637),"瑞芳區":(121.8028,25.1085),
    "土城區":(121.4452,24.9740),"蘆洲區":(121.4766,25.0866),"林口區":(121.3889,25.0789),
    "深坑區":(121.6145,24.9916),"石碇區":(121.6603,24.9762),"坪林區":(121.7148,24.9347),
    "三芝區":(121.5031,25.2559),"石門區":(121.5690,25.2937),"八里區":(121.3964,25.1564),
    "平溪區":(121.7379,25.0213),"雙溪區":(121.8686,25.0417),"貢寮區":(121.9035,25.0247),
    "金山區":(121.6378,25.2238),"萬里區":(121.6890,25.1805),"烏來區":(121.5487,24.8680),
    "泰山區":(121.4320,25.0564),"五股區":(121.4487,25.0780),
}

_BASELINE_SPEEDS: dict[str, float] = {
    "板橋區":50,"三重區":50,"中和區":50,"永和區":50,"新莊區":50,
    "土城區":50,"蘆洲區":50,"新店區":50,"樹林區":50,"汐止區":50,
    "泰山區":50,"五股區":50,"林口區":60,
    "淡水區":60,"三峽區":60,"鶯歌區":60,"深坑區":60,
    "瑞芳區":60,"石碇區":60,"坪林區":60,"烏來區":60,
    "三芝區":60,"石門區":60,"八里區":60,
    "平溪區":60,"雙溪區":60,"貢寮區":60,
    "金山區":60,"萬里區":60,
}
_DEFAULT_BASELINE = 50.0
_CACHE_TTL = 900  # 15 分鐘
_TOKEN_TTL = 3300  # 55 分鐘

_lock = threading.Lock()
_token: Optional[str] = None
_token_ts: float = 0.0
_factors: dict[str, float] = {}  # district -> factor
_factors_ts: float = 0.0
_congestion: float = 0.0


def _nearest_district(lng: float, lat: float) -> Optional[str]:
    best, best_d = None, float("inf")
    for d, (lo, la) in _DIST_COORDS.items():
        dist = (lo - lng) ** 2 + (la - lat) ** 2
        if dist < best_d:
            best_d = dist; best = d
    return best


def _get_token() -> Optional[str]:
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
            _token = r.json()["access_token"]
            _token_ts = time.time()
            return _token
        except Exception as e:
            log.warning(f"TDX token error: {e}")
            return None


def _fetch_json(token: str, url: str) -> list[dict]:
    """呼叫 TDX API，回傳資料串列。失敗回傳空串列。"""
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.status_code != 200:
            log.debug(f"TDX {url.split('v2/')[-1][:50]}: {r.status_code}")
            return []
        d = r.json()
        if isinstance(d, list):
            return d
        for key in ("VDLives", "VDs", "VDList"):
            if key in d:
                return d[key]
        return []
    except Exception as e:
        log.debug(f"TDX fetch error: {e}")
        return []


def refresh() -> bool:
    """強制重新取得 TDX VD 即時路況，更新行政區係數快取。
    步驟：
      1. 取靜態 VD（有座標）→ 建立 VDID→(lng,lat) 對照表
      2. 取即時 VD（有速度）→ 與靜態對照表合併
    取台北市＋桃園市作為大新北都會區代理（新北市免費方案未提供 VD）。
    """
    global _factors, _factors_ts, _congestion
    token = _get_token()
    if not token:
        return False
    try:
        BASE = "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic"

        # 步驟 1：靜態 VD 座標（VDID → (lng, lat)）
        coord_map: dict[str, tuple[float, float]] = {}
        for city in ("Taipei", "Taoyuan"):
            for vd in _fetch_json(token, f"{BASE}/VD/City/{city}?$format=JSON"):
                vid = vd.get("VDID")
                lng = vd.get("PositionLon")
                lat = vd.get("PositionLat")
                if vid and lng and lat:
                    coord_map[vid] = (lng, lat)

        if not coord_map:
            log.warning("TDX: 未取得靜態 VD 座標")
            return False

        # 步驟 2：即時 VD 速度（VDID → avg_speed）
        dist_speeds: dict[str, list[float]] = {}
        for city in ("Taipei", "Taoyuan"):
            for vd in _fetch_json(token, f"{BASE}/Live/VD/City/{city}?$format=JSON"):
                vid = vd.get("VDID")
                if not vid or vid not in coord_map:
                    continue
                lng, lat = coord_map[vid]
                speeds: list[float] = []
                for lf in vd.get("LinkFlows", []):
                    for lane in lf.get("Lanes", []):
                        spd = lane.get("Speed") or lane.get("AvgSpeed")
                        if spd and float(spd) > 0:
                            speeds.append(float(spd))
                if not speeds:
                    continue
                dist = _nearest_district(lng, lat)
                if dist:
                    dist_speeds.setdefault(dist, []).append(sum(speeds) / len(speeds))

        if not dist_speeds:
            log.warning("TDX: 未取得任何有效速度資料")
            return False

        # 計算各行政區路況係數
        new_factors: dict[str, float] = {}
        for dist, spds in dist_speeds.items():
            avg_spd = sum(spds) / len(spds)
            baseline = _BASELINE_SPEEDS.get(dist, _DEFAULT_BASELINE)
            factor = avg_spd / baseline
            new_factors[dist] = max(0.3, min(1.2, factor))

        with _lock:
            _factors = new_factors
            _factors_ts = time.time()
            all_f = list(new_factors.values())
            _congestion = max(0.0, min(1.0, 1.0 - (sum(all_f) / len(all_f)))) if all_f else 0.0

        log.info(f"TDX updated: {len(new_factors)} districts, {len(coord_map)} VDs, congestion={_congestion:.2f}")
        return True
    except Exception as e:
        log.warning(f"TDX refresh error: {e}")
        return False


def _ensure_fresh():
    if time.time() - _factors_ts > _CACHE_TTL:
        refresh()


def get_district_factors() -> dict[str, float]:
    _ensure_fresh()
    with _lock:
        return dict(_factors)


def get_pair_factor(origin: str, dest: str) -> float:
    f = get_district_factors()
    fo = f.get(origin, 1.0)
    fd = f.get(dest, 1.0)
    return (fo + fd) / 2


def get_congestion_level() -> float:
    _ensure_fresh()
    with _lock:
        return _congestion


def apply_to_matrix(
    arr: np.ndarray,
    points: list[tuple[float, float]],
) -> np.ndarray:
    """依行政區路況係數調整 OSRM 行駛時間矩陣（就地修改副本）。
    factor < 1 表示塞車 → 行駛時間除以 factor（時間變長）。
    """
    factors = get_district_factors()
    if not factors:
        return arr  # 無資料，不調整

    # 每個點對應的行政區 factor
    point_factors = []
    for lng, lat in points:
        d = _nearest_district(lng, lat)
        point_factors.append(factors.get(d, 1.0) if d else 1.0)

    result = arr.copy().astype(np.float32)
    n = len(points)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            f = (point_factors[i] + point_factors[j]) / 2
            if f < 0.99:  # 有塞車才調整，避免不必要計算
                result[i][j] = result[i][j] / f
    return result.astype(np.uint32)


# ── 靜態時段路況係數（方向 A）────────────────────────────────────────
# 基於新北市通勤規律經驗值；2 週後由 TDX ETag 歷史資料自動校正
_STATIC_TIME_FACTORS: dict[int, float] = {
    5:  0.95,   # 05:xx 清晨，幾乎順暢
    6:  0.88,   # 06:xx 早班出門，開始變慢
    7:  0.52,   # 07:xx 早峰嚴重
    8:  0.48,   # 08:xx 早峰最重（長照去程高峰）
    9:  0.72,   # 09:xx 漸退
    10: 0.88,
    11: 0.92,
    12: 0.85,   # 午間稍慢
    13: 0.92,
    14: 0.93,
    15: 0.78,   # 下午峰開始
    16: 0.62,   # 下午峰（長照回程高峰）
    17: 0.50,   # 下午峰最重
    18: 0.78,
    19: 0.90,
    20: 0.95,
}
_DEFAULT_TIME_FACTOR = 0.97   # 其他時段（深夜/凌晨）


def get_time_factor(hour_of_day: int) -> float:
    """依時段回傳路況係數（<1.0 表示塞車，行程時間需除以此值變長）。
    hour_of_day: 0–23（台灣時間）
    優先使用 TDX ETag 歷史均值（Phase 2），無資料時回退靜態經驗值。
    """
    return _STATIC_TIME_FACTORS.get(hour_of_day, _DEFAULT_TIME_FACTOR)


def get_time_factor_for_sec(seconds_of_day: int) -> float:
    """依一天中的秒數（0=午夜）回傳路況係數。"""
    return get_time_factor(max(0, seconds_of_day) // 3600)


def scale_matrix_for_time(arr, seconds_of_day: int):
    """依時段係數縮放 OSRM 行駛時間矩陣（塞車→時間變長）。
    arr: np.ndarray (uint32), 就地回傳副本。
    """
    import numpy as np
    factor = get_time_factor_for_sec(seconds_of_day)
    if factor >= 0.99:   # 幾乎順暢，不調整
        return arr
    scaled = (arr.astype(np.float32) / factor).astype(np.uint32)
    # 保留 UNROUTABLE 標記不變
    scaled[arr >= 9_999_999] = 9_999_999
    return scaled
