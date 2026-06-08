"""地理編碼(DB 優先 + 地址簿)。

流程:
1. 先查 address_alias(原始描述)→ 命中即用對應門牌座標,**不打 Map8**。
   別名指向 NULL 表示「查過查無」,也直接回傳,避免重複呼叫。
2. 未命中才呼叫 provider(map8 / nominatim)取得校正後地址 + 座標。
3. 以「校正後地址」為鍵 upsert address_point;同一門牌的多種原始描述
   會各自建立 alias 指向同一個 address_point(多描述、單門牌)。

對外維持 geocode(db, raw) 介面,回傳 GeoResult(found / lng / lat / precision / standardized)。
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.address import AddressAlias, AddressPoint
from app.services import map8


@dataclass
class GeoResult:
    found: bool
    lng: float | None = None
    lat: float | None = None
    precision: str | None = None
    standardized: str | None = None


# --- Nominatim(備援 provider)---------------------------------------------

def _variants(address: str) -> list[str]:
    a = address.strip()
    out = [a]
    out.append(re.sub(r"號.*$", "號", a))
    out.append(re.sub(r"[0-9０-９]+號?.*$", "", a))
    out.append(re.sub(r"[一二三四五六七八九十0-9]+段.*$", "", a))
    m = re.match(r"^(.+?[市縣].+?[區鄉鎮市])", a)
    if m:
        out.append(m.group(1))
    seen: list[str] = []
    for v in out:
        v = v.strip()
        if v and v not in seen:
            seen.append(v)
    return seen


def _nominatim_geocode(address: str) -> dict | None:
    for i, q in enumerate(_variants(address)):
        params = urllib.parse.urlencode(
            {"q": q, "format": "json", "limit": 1, "countrycodes": "tw"}
        )
        url = f"{settings.NOMINATIM_URL}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": settings.GEOCODER_USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
        except Exception:
            data = []
        time.sleep(settings.GEOCODE_RATE_SLEEP)
        if data:
            return {
                "lng": float(data[0]["lon"]),
                "lat": float(data[0]["lat"]),
                "precision": "exact" if i == 0 else "approx",
                "formatted": q,
                "city": None,
                "town": None,
            }
    return None


def _provider_geocode(address: str) -> dict | None:
    if settings.GEOCODER_PROVIDER == "map8" and settings.MAP8_API_KEY:
        try:
            return map8.geocode_address(address)
        except Exception:  # noqa: BLE001
            return None
    return _nominatim_geocode(address)


# --- 對外:DB 優先地理編碼 --------------------------------------------------

def _result_from_point(p: AddressPoint) -> GeoResult:
    return GeoResult(True, p.lng, p.lat, p.precision, p.standardized_address)


def geocode(db: Session, raw_address: str) -> GeoResult:
    raw = (raw_address or "").strip()
    if not raw:
        return GeoResult(False)

    # 1) 先查別名(原始描述)
    alias = db.get(AddressAlias, raw)
    if alias is not None:
        if alias.address_point_id is None:
            return GeoResult(False)                       # 已知查無
        point = db.get(AddressPoint, alias.address_point_id)
        if point:
            return _result_from_point(point)

    # 2) 未命中 → 呼叫 provider
    hit = _provider_geocode(raw)
    if not hit:
        db.merge(AddressAlias(raw_address=raw, address_point_id=None))  # 快取查無
        db.commit()
        return GeoResult(False)

    std = (hit.get("formatted") or raw).strip()
    provider = settings.GEOCODER_PROVIDER

    # 3) 以校正後地址 upsert 門牌(多描述共用同一門牌)
    point = db.scalar(select(AddressPoint).where(AddressPoint.standardized_address == std))
    if point is None:
        point = AddressPoint(
            standardized_address=std,
            lng=hit["lng"], lat=hit["lat"],
            precision=hit.get("precision"),
            city=hit.get("city"), town=hit.get("town"),
            source=provider,
        )
        db.add(point)
        db.flush()  # 取得 point.id

    db.merge(AddressAlias(raw_address=raw, address_point_id=point.id))
    db.commit()
    return _result_from_point(point)
