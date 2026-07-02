"""地址編碼勘誤(geo audit)—— 未派/離群座標先自動校正再重派。

規則:凡座標「缺失」或「離當日營運區中位點 > 40km」(疑似被編到他縣市)者,
產生多個修正版地址重新編碼,挑「離營運區最近且 < 40km」的結果採用——用營運區
當消歧,天然濾掉錯縣市的誤編。命中即回寫訂單座標 + 快取別名(日後同址免修)。

自動接進「匯入後標準流程」(import_schedule 末端呼叫);另開 POST /orders/geo-audit 手動觸發。
"""
from __future__ import annotations

import math
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.address import AddressAlias, AddressPoint
from app.models.order import Order
from app.services.geocode import _provider_geocode
from app.core.config import settings

OUTLIER_KM = 40.0                       # 與 comparison.GEO_OUTLIER_KM 一致
FALLBACK_CITIES = ["新北市", "臺北市", "台北市", "基隆市"]   # 營運區候選縣市(補前綴用)
_PAREN = re.compile(r"[\(（].*?[\)）]")
_FLOOR = re.compile(r"\d+\s*[樓Ff].*$")
_FW = str.maketrans("０１２３４５６７８９", "0123456789")


def _km(lng1, lat1, lng2, lat2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _median_centroid(pts: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not pts:
        return None
    xs = sorted(p[0] for p in pts)
    ys = sorted(p[1] for p in pts)
    m = len(xs) // 2
    return (xs[m], ys[m])


def _has_city(addr: str) -> bool:
    return ("市" in addr[:4]) or ("縣" in addr[:4])


def _clean(addr: str) -> str:
    """去括號說明 / 樓層 / 全形數字;修常見 OCR 筆誤(I/l→1、医→醫)。"""
    a = _PAREN.sub("", addr or "")
    a = _FLOOR.sub("", a)
    a = a.translate(_FW).replace("医", "醫")
    a = re.sub(r"[IlＩｌ](?=[號段巷弄])", "1", a)     # 常德街I號 → 常德街1號
    return a.strip()


def _facility(addr: str) -> str | None:
    """取括號內設施名(如「(台大醫院門口)」→ 台大醫院)。"""
    m = _PAREN.search(addr or "")
    if not m:
        return None
    inner = re.sub(r"[\(（\)）]", "", m.group(0))
    inner = re.sub(r"(門口|大門|正門|樓|櫃台|對面|旁|舊院區|西址|東址)$", "", inner).strip()
    return inner or None


def _variants(addr: str, cities: list[str]) -> list[str]:
    base = _clean(addr)
    outs: list[str] = [addr.strip(), base]
    if not _has_city(base):
        outs += [c + base for c in cities]
    fac = _facility(addr)
    if fac:
        outs.append(fac)
        outs += [c + fac for c in cities]
    seen, uniq = set(), []
    for v in outs:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def _best_fix(addr: str, centroid: tuple[float, float], cities: list[str]) -> dict | None:
    """回傳離營運區最近且 < 40km 的編碼結果;找不到則 None。"""
    best = None
    for v in _variants(addr, cities):
        try:
            r = _provider_geocode(v)
        except Exception:  # noqa: BLE001
            r = None
        if not r or r.get("lng") is None:
            continue
        d = _km(r["lng"], r["lat"], *centroid)
        if d <= OUTLIER_KM and (best is None or d < best[0]):
            best = (d, r, v)
    if not best:
        return None
    _, r, v = best
    return {"lng": r["lng"], "lat": r["lat"],
            "std": (r.get("formatted") or v).strip(),
            "precision": r.get("precision"), "km": round(best[0], 1), "query": v}


def _upsert(db: Session, raw_addr: str, fix: dict) -> None:
    """把校正結果寫進地址簿(門牌 + 原始描述別名,覆蓋錯誤別名)。"""
    pt = db.scalar(select(AddressPoint).where(AddressPoint.standardized_address == fix["std"]))
    if pt is None:
        pt = AddressPoint(standardized_address=fix["std"], lng=fix["lng"], lat=fix["lat"],
                          precision=fix.get("precision"), source=settings.GEOCODER_PROVIDER)
        db.add(pt)
        db.flush()
    db.merge(AddressAlias(raw_address=raw_addr, address_point_id=pt.id))


def audit_day(db: Session, service_date: date, apply: bool = True) -> dict:
    """對某日訂單做地址勘誤:缺座標或離群(>40km)者嘗試校正並(可選)回寫。"""
    orders = list(db.scalars(select(Order).where(Order.service_date == service_date)).all())
    pts = [(o.pickup_lng, o.pickup_lat) for o in orders if o.pickup_lng is not None]
    pts += [(o.dropoff_lng, o.dropoff_lat) for o in orders if o.dropoff_lng is not None]
    centroid = _median_centroid(pts)
    rep = {"service_date": service_date.isoformat(), "checked": 0,
           "corrected": [], "failed": [], "centroid": centroid}
    if centroid is None:
        return rep   # 全日無任何座標,無從消歧

    # 當日縣市候選:取現有門牌 city(近營運區),補預設
    cities = []
    for (c,) in db.execute(select(AddressPoint.city.distinct()).where(
            AddressPoint.city.is_not(None))).all():
        if c and c not in cities:
            cities.append(c)
    cities = [c for c in cities if c] or []
    cities = list(dict.fromkeys([*FALLBACK_CITIES, *cities]))

    for o in orders:
        for side in ("pickup", "dropoff"):
            lng = getattr(o, f"{side}_lng")
            lat = getattr(o, f"{side}_lat")
            addr = getattr(o, f"{side}_address")
            missing = lng is None or lat is None
            outlier = (not missing) and _km(lng, lat, *centroid) > OUTLIER_KM
            if not (missing or addr and outlier):
                continue
            rep["checked"] += 1
            fix = _best_fix(addr, centroid, cities) if addr else None
            if fix:
                if apply:
                    setattr(o, f"{side}_lng", fix["lng"])
                    setattr(o, f"{side}_lat", fix["lat"])
                    _upsert(db, addr, fix)
                rep["corrected"].append({
                    "order_id": o.id, "side": side, "address": addr,
                    "old": None if missing else [round(lng, 5), round(lat, 5)],
                    "new": [round(fix["lng"], 5), round(fix["lat"], 5)],
                    "km_to_area": fix["km"], "reason": "缺座標" if missing else "離群",
                })
            else:
                rep["failed"].append({
                    "order_id": o.id, "side": side, "address": addr,
                    "reason": "缺座標" if missing else "離群", "note": "勘誤仍無營運區內結果",
                })
    if apply:
        db.commit()
    rep["corrected_count"] = len(rep["corrected"])
    rep["failed_count"] = len(rep["failed"])
    return rep
