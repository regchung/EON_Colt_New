"""車隊「班表」匯入:把人工派遣結果(每列含乘客+起迄+時段+指派車牌/駕駛)
轉為「訂單(done)+ 人工派遣歷史(已轉至正式單)」,供逐車對比/成效分析使用。

與長照平台檔(history_import)差異:
- 本檔**無座標**,需呼叫 geocode(地址簿優先 → Map8 備援)。
- 本檔**無訂單編號**,以「SCH-<日期>-<序>」生成穩定編號(同日重匯前先清當日)。
- 訂單類型「假單」(測試/占位,如『小驢駒先生A』)預設略過;正常 + 候補納入。

服務日期為民國 7 碼(如 1150623 → 2026-06-23)。
派遣原則 4:福祉與否「只看車型需求是否含『福祉』」。
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dispatch_history import DispatchHistory
from app.models.driver import Driver
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import geocode as geocode_svc

TW = timezone(timedelta(hours=8))
SERVED = "已轉至正式單"          # dispatch_history.status:逐車對比以此為人工基準
SKIP_ORDER_TYPES = {"假單"}     # 測試/占位單,不納入人工派遣基準
AVG_KMPH = 25.0                 # 載客里程→預估分鐘(僅供參考欄)


def _s(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _f(v) -> float | None:
    s = _s(v)
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


def _i(v) -> int | None:
    f = _f(v)
    return int(f) if f is not None else None


def _find_col(cols: list[str], *needles: str) -> str | None:
    """回傳第一個「包含所有 needles 子字串」的欄名(容忍換行/空白雜訊)。"""
    for c in cols:
        flat = str(c).replace("\n", " ")
        if all(n in flat for n in needles):
            return c
    return None


def _consent_col(cols: list[str]) -> str | None:
    """找「共乘同意」欄:優先明確欄名;否則取含『共乘』但非『組別/訂單編號』的欄。"""
    for pref in ("共乘同意", "願意共乘", "共乘意願", "是否共乘"):
        c = _find_col(cols, pref)
        if c:
            return c
    for c in cols:
        s = str(c)
        if "共乘" in s and "組別" not in s and "訂單" not in s:
            return c
    return None


def _is_consent(val) -> bool:
    """規則:值含『同意』且非『不同意』→ 同意;其餘(含空白/未知)→ 不同意(預設)。"""
    s = str(val).strip() if val is not None else ""
    return ("同意" in s) and ("不同意" not in s)


def _roc_date(s: str | None) -> date | None:
    """民國 7 碼(1150623)→ 西元 date。"""
    s = _s(s)
    if not s or len(s) < 7 or not s.isdigit():
        return None
    yyyy = int(s[:3]) + 1911
    try:
        return date(yyyy, int(s[3:5]), int(s[5:7]))
    except ValueError:
        return None


def _read_df(filename: str, content: bytes) -> pd.DataFrame:
    engine = "xlrd" if (filename or "").lower().endswith(".xls") else "openpyxl"
    df = pd.read_excel(io.BytesIO(content), sheet_name=0, header=0, dtype=str, engine=engine)
    return df.where(pd.notna(df), None)


def import_schedule(db: Session, content: bytes, filename: str,
                    replace_date: bool = True) -> dict:
    df = _read_df(filename, content)
    cols = list(df.columns)
    C = {
        "type": _find_col(cols, "車型需求"),
        "fleet": _find_col(cols, "子車隊"),
        "name": next((c for c in cols if str(c).strip() == "姓名"), None),
        "date": _find_col(cols, "服務日期"),
        "sh": _find_col(cols, "起始時段", "小時"),
        "sm": _find_col(cols, "起始時段", "分鐘"),
        "paddr": _find_col(cols, "起點地址"),
        "daddr": _find_col(cols, "迄點地址"),
        "wheel": _find_col(cols, "承載輪椅"),
        "dist": _find_col(cols, "載客里程"),
        "pax": _find_col(cols, "乘客數"),
        "driver": _find_col(cols, "駕駛姓名"),
        "plate": _find_col(cols, "車牌號碼"),
        "dphone": _find_col(cols, "駕駛電話"),
        "otype": _find_col(cols, "訂單類型"),
        # 共乘同意來源(優先序):固定趟(派遣時凌駕)> 共乘組別有值(實際成組→推定同意)> 共乘欄位含「同意」> 預設不同意。
        "consent": _consent_col(cols),
        "pool_group": _find_col(cols, "共乘組別"),
    }
    missing = [k for k in ("date", "paddr", "daddr", "plate") if not C[k]]
    if missing:
        return {"error": f"班表缺少必要欄位:{missing}(實際欄名={cols})"}

    rows = df.to_dict(orient="records")
    rep = {
        "rows": len(rows), "imported": 0, "skipped_fake": 0, "errors": [],
        "geocoded": 0, "geocode_miss": 0, "vehicles_created": 0, "drivers_created": 0,
        "dates": [], "deleted_orders": 0, "deleted_history": 0,
    }

    # 解析後先決定涉及的服務日期(供 replace 清檔)
    parsed = []
    for idx, r in enumerate(rows):
        otype = _s(r.get(C["otype"])) if C["otype"] else None
        if otype in SKIP_ORDER_TYPES:
            rep["skipped_fake"] += 1
            continue
        sd = _roc_date(r.get(C["date"]))
        if sd is None:
            rep["errors"].append({"row": idx + 2, "error": "服務日期無法解析"})
            continue
        parsed.append((idx, r, sd))
    dates = sorted({sd for _, _, sd in parsed})
    rep["dates"] = [d.isoformat() for d in dates]

    if replace_date and dates:
        for d in dates:
            rep["deleted_orders"] += db.query(Order).filter(Order.service_date == d).delete()
            rep["deleted_history"] += db.query(DispatchHistory).filter(
                DispatchHistory.service_date == d).delete()
        db.commit()

    geo_cache: dict[str, tuple[float | None, float | None]] = {}

    def geo(addr: str | None) -> tuple[float | None, float | None]:
        a = _s(addr)
        if not a:
            return (None, None)
        if a in geo_cache:
            return geo_cache[a]
        res = geocode_svc.geocode(db, a)
        out = (res.lng, res.lat) if res.found else (None, None)
        if res.found:
            rep["geocoded"] += 1
        else:
            rep["geocode_miss"] += 1
        geo_cache[a] = out
        return out

    seq = 0
    for idx, r, sd in parsed:
        try:
            seq += 1
            son = f"SCH-{sd.strftime('%Y%m%d')}-{seq:04d}"
            fleet = _s(r.get(C["fleet"])) if C["fleet"] else None
            passenger = _s(r.get(C["name"])) if C["name"] else None
            paddr = _s(r.get(C["paddr"]))
            daddr = _s(r.get(C["daddr"]))
            # 共乘同意(優先序):共乘組別有值(實際成組)→ 推定同意;否則共乘欄位含「同意」→ 同意;皆無 → 不同意。
            # (固定趟的「凌駕」在派遣層處理:fixed_pins → 強制可併,不受此同意值限制。)
            consent = bool(
                (C["pool_group"] and _s(r.get(C["pool_group"])))
                or (C["consent"] and _is_consent(r.get(C["consent"])))
            )
            if not (paddr and daddr):
                rep["errors"].append({"row": idx + 2, "error": "缺起點/迄點地址"})
                continue

            hh = _i(r.get(C["sh"])) or 0 if C["sh"] else 0
            mm = _i(r.get(C["sm"])) or 0 if C["sm"] else 0
            pickup_dt = datetime(sd.year, sd.month, sd.day, min(hh, 23), min(mm, 59), tzinfo=TW)

            type_req = _s(r.get(C["type"])) if C["type"] else None
            welfare = bool(type_req and "福祉" in type_req)
            pax = (_i(r.get(C["pax"])) or 1) if C["pax"] else 1
            wheelchair = 1 if (C["wheel"] and _s(r.get(C["wheel"])) == "有") else 0
            dist_km = (_f(r.get(C["dist"])) or 0) if C["dist"] else 0
            plate = _s(r.get(C["plate"]))
            driver_name = _s(r.get(C["driver"])) if C["driver"] else None
            driver_phone = _s(r.get(C["dphone"])) if C["dphone"] else None

            p_lng, p_lat = geo(paddr)
            d_lng, d_lat = geo(daddr)

            # --- 確保車輛存在(以車牌;對比以 vehicles.plate 取車)---
            vehicle = None
            if plate:
                vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == plate))
                if vehicle is None:
                    vehicle = Vehicle(plate=plate, type="welfare" if welfare else "normal",
                                      seats=max(1, pax), active=True, home_fleet=fleet,
                                      depot_lng=p_lng, depot_lat=p_lat,
                                      start_lng=p_lng, start_lat=p_lat,
                                      end_lng=p_lng, end_lat=p_lat)
                    db.add(vehicle)
                    db.flush()
                    rep["vehicles_created"] += 1
                elif welfare and vehicle.type != "welfare":
                    vehicle.type = "welfare"

            # --- 確保駕駛存在(以姓名)---
            if driver_name:
                drv = db.scalar(select(Driver).where(Driver.name == driver_name))
                if drv is None:
                    drv = Driver(name=driver_name, phone=driver_phone, home_fleet=fleet,
                                 vehicle_id=vehicle.id if vehicle else None, active=True)
                    db.add(drv)
                    db.flush()
                    rep["drivers_created"] += 1

            # --- 訂單(status=done)---
            order = Order(
                source_order_no=son, fleet=fleet, service_date=sd, pickup_time=pickup_dt,
                passenger_name=passenger, pickup_address=paddr, dropoff_address=daddr,
                pickup_lng=p_lng, pickup_lat=p_lat, dropoff_lng=d_lng, dropoff_lat=d_lat,
                pax=pax, vehicle_type="welfare" if welfare else "normal",
                need_wheelchair=bool(wheelchair),
                allow_pool=bool(consent), status="done",   # A:預設不同意(consent None/False → 不併)
                pool_consent_at=pickup_dt if consent else None,
                pool_consent_by="班表匯入" if consent else None,
                assigned_vehicle_id=vehicle.id if vehicle else None,
            )
            db.add(order)

            # --- 人工派遣歷史(status=SERVED,逐車對比基準)---
            est_min = round(dist_km / AVG_KMPH * 60) if dist_km else None
            db.add(DispatchHistory(
                source_order_no=son, fleet=fleet, service_date=sd, pickup_time=pickup_dt,
                plate=plate, driver_name=driver_name, driver_phone=driver_phone,
                pickup_address=paddr, dropoff_address=daddr,
                pickup_lng=p_lng, pickup_lat=p_lat, dropoff_lng=d_lng, dropoff_lat=d_lat,
                vehicle_type_req=type_req, pax=pax, wheelchair_count=wheelchair,
                distance_m=dist_km * 1000 if dist_km else None, est_minutes=est_min,
                status=SERVED, pool_consent=consent,
            ))
            rep["imported"] += 1
        except Exception as e:  # noqa: BLE001
            rep["errors"].append({"row": idx + 2, "error": str(e)})

    db.commit()

    # 匯入後自動地址編碼勘誤(規則:判未派前先校正離群/缺失座標,避免誤編他縣市被當未派)
    try:
        from app.services import geo_audit
        rep["geo_audit"] = {}
        for d in dates:
            ga = geo_audit.audit_day(db, d, apply=True)
            rep["geo_audit"][d.isoformat()] = {
                "corrected": ga.get("corrected_count", 0),
                "failed": ga.get("failed_count", 0),
            }
    except Exception as e:  # noqa: BLE001
        rep["geo_audit_error"] = str(e)
    return rep
