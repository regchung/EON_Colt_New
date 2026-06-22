"""車隊資源名冊匯入:司機/車輛主檔 → 回填真實座位、福祉能力、出車起點/收車終點。

來源檔欄位(長照司機工作資料管理):
  駕駛姓名 子車隊名稱 車牌號碼 汽車廠牌 車型 長照車型
  經度 緯度(出車起點) End經度 End緯度(收車終點) 地址 乘客數 輪椅數

語意:
- 「經度/緯度」= 車輛當日出發位置;「End經度/End緯度」= 當日最終返回位置。
- 「乘客數」= 實際可載客數(已扣司機/輪椅佔位),作為 VROOM capacity(座位)。
- 「長照車型」≠「小型」(即輪椅數>0)→ 福祉車(welfare,具輪椅技能)。
冪等:以車牌 upsert 車輛、以姓名 upsert 司機。
"""
from __future__ import annotations

import io

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.vehicle import Vehicle


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


def _read_rows(filename: str, content: bytes) -> list[dict]:
    engine = "xlrd" if (filename or "").lower().endswith(".xls") else "openpyxl"
    df = pd.read_excel(io.BytesIO(content), sheet_name=0, header=0, dtype=str, engine=engine)
    df = df.where(pd.notna(df), None)
    df.columns = [str(c).strip() for c in df.columns]
    return df.to_dict(orient="records")


def import_fleet(db: Session, content: bytes, filename: str) -> dict:
    rows = _read_rows(filename, content)
    rep = {
        "rows": len(rows), "vehicles_created": 0, "vehicles_updated": 0,
        "drivers_created": 0, "drivers_updated": 0,
        "welfare": 0, "normal": 0, "errors": [],
    }

    for idx, r in enumerate(rows):
        try:
            plate = _s(r.get("車牌號碼"))
            if not plate:
                rep["errors"].append({"row": idx + 2, "error": "缺車牌號碼"})
                continue

            fleet = _s(r.get("子車隊名稱"))
            ltc = _s(r.get("長照車型"))          # 福祉車 / 旅行家 / 小型
            wheelchair = _i(r.get("輪椅數")) or 0
            welfare = (ltc is not None and ltc != "小型") or wheelchair > 0
            seats = _i(r.get("乘客數")) or 4      # 實際可載客數 = VROOM capacity
            s_lng, s_lat = _f(r.get("經度")), _f(r.get("緯度"))         # 出車起點
            e_lng, e_lat = _f(r.get("End經度")), _f(r.get("End緯度"))   # 收車終點

            vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == plate))
            created = vehicle is None
            if created:
                vehicle = Vehicle(plate=plate, active=True)
                db.add(vehicle)
            vehicle.type = "welfare" if welfare else "normal"
            vehicle.seats = seats
            vehicle.wheelchair = wheelchair
            vehicle.start_lng, vehicle.start_lat = s_lng, s_lat
            vehicle.end_lng, vehicle.end_lat = e_lng, e_lat
            if fleet:
                vehicle.home_fleet = fleet
            # depot 作為退化備援:若空,以出車起點補上
            if vehicle.depot_lng is None and s_lng is not None:
                vehicle.depot_lng, vehicle.depot_lat = s_lng, s_lat
            db.flush()
            rep["vehicles_created" if created else "vehicles_updated"] += 1
            rep["welfare" if welfare else "normal"] += 1

            name = _s(r.get("駕駛姓名"))
            if name:
                drv = db.scalar(select(Driver).where(Driver.name == name))
                d_created = drv is None
                if d_created:
                    drv = Driver(name=name, active=True)
                    db.add(drv)
                drv.vehicle_id = vehicle.id
                if fleet:
                    drv.home_fleet = fleet
                db.flush()
                rep["drivers_created" if d_created else "drivers_updated"] += 1
        except Exception as e:  # noqa: BLE001
            rep["errors"].append({"row": idx + 2, "error": str(e)})

    db.commit()
    return rep


def reconcile_fleet(db: Session, content: bytes, filename: str) -> dict:
    """依名冊對帳:檔內車牌/姓名 → 啟用(suspended=False);不在檔內 → 停派(suspended=True)。

    車輛以「車牌號碼」配對、司機以「駕駛姓名」配對。回傳異動統計。
    """
    rows = _read_rows(filename, content)
    # 車牌 → (乘客數, 輪椅數):供更新車輛座位/輪椅數
    file_specs: dict[str, tuple[int, int]] = {}
    for r in rows:
        p = _s(r.get("車牌號碼"))
        if p:
            file_specs[p] = (_i(r.get("乘客數")) or 4, _i(r.get("輪椅數")) or 0)
    file_plates = set(file_specs)
    file_names = {n for r in rows if (n := _s(r.get("駕駛姓名")))}

    rep = {
        "file_plates": len(file_plates), "file_names": len(file_names),
        "vehicles_suspended": 0, "vehicles_activated": 0,
        "drivers_suspended": 0, "drivers_activated": 0,
        "vehicles_specs_updated": 0,
        "suspended_vehicles": [], "suspended_drivers": [],
    }
    for v in db.scalars(select(Vehicle)).all():
        should = (_s(v.plate) not in file_plates)
        if v.suspended != should:
            v.suspended = should
            rep["vehicles_suspended" if should else "vehicles_activated"] += 1
        if should:
            rep["suspended_vehicles"].append(v.plate)
        else:
            # 名冊內車輛:用名冊的乘客數/輪椅數更新座位與輪椅數
            seats, wc = file_specs[_s(v.plate)]
            if v.seats != seats or v.wheelchair != wc:
                v.seats, v.wheelchair = seats, wc
                rep["vehicles_specs_updated"] += 1
    for d in db.scalars(select(Driver)).all():
        should = (_s(d.name) not in file_names)
        if d.suspended != should:
            d.suspended = should
            rep["drivers_suspended" if should else "drivers_activated"] += 1
        if should:
            rep["suspended_drivers"].append(d.name)
    db.commit()
    return rep
