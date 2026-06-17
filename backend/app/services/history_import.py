"""長照車隊平台匯出檔匯入:同時建立訂單 + 人工派遣歷史 + 自建車/司機 + 灌地址簿。

隱私:**不儲存身分證號**(從 raw 移除);電話照存(派遣需用)。
座標:檔案已含上/下車經緯度,匯入時直接採用,不再呼叫地理編碼。
冪等:以「訂單編號」(source_order_no)為鍵 upsert 訂單與歷史。
"""
from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.address import AddressAlias, AddressPoint
from app.models.dispatch_history import DispatchHistory
from app.models.driver import Driver
from app.models.order import Order
from app.models.vehicle import Vehicle

TW = timezone(timedelta(hours=8))
PII_DROP = {"乘客身分證號"}  # 不入庫的高敏欄位

# 來源狀態 → 我方 orders.status
STATUS_MAP = {"已轉至正式單": "done", "已重置": "canceled"}


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


def _dt(v) -> datetime | None:
    s = _s(v)
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TW)
        except ValueError:
            continue
    return None


def _is_welfare(type_req: str | None, wheelchair: int | None) -> bool:
    return bool((type_req and "福祉" in type_req) or (wheelchair and wheelchair > 0))


def _read_rows(filename: str, content: bytes) -> list[dict]:
    name = (filename or "").lower()
    engine = "xlrd" if name.endswith(".xls") else "openpyxl"
    df = pd.read_excel(io.BytesIO(content), sheet_name=0, header=0, dtype=str, engine=engine)
    df = df.where(pd.notna(df), None)
    return df.to_dict(orient="records")


def _upsert_address(db: Session, addr: str | None, lng, lat, city, town):
    """把檔案提供的真實座標灌進地址簿(alias→point),日後同址免再 geocode。"""
    if not addr or lng is None or lat is None:
        return
    addr = addr.strip()
    point = db.scalar(select(AddressPoint).where(AddressPoint.standardized_address == addr))
    if point is None:
        point = AddressPoint(
            standardized_address=addr, lng=lng, lat=lat,
            precision="history", city=city, town=town, source="history",
        )
        db.add(point)
        db.flush()
    if db.get(AddressAlias, addr) is None:
        db.add(AddressAlias(raw_address=addr, address_point_id=point.id))


def import_history(db: Session, content: bytes, filename: str) -> dict:
    rows = _read_rows(filename, content)
    report = {
        "rows": len(rows), "orders_created": 0, "orders_updated": 0,
        "history_created": 0, "vehicles_created": 0, "drivers_created": 0,
        "errors": [],
    }

    veh_cache: dict[str, Vehicle] = {}
    drv_cache: dict[str, Driver] = {}

    for idx, r in enumerate(rows):
        try:
            son = _s(r.get("訂單編號"))
            pickup_dt = _dt(r.get("預約用車時間"))
            pickup_addr = _s(r.get("[上車]Address"))
            dropoff_addr = _s(r.get("[下車]Address"))
            if not (son and pickup_dt and pickup_addr and dropoff_addr):
                report["errors"].append({"row": idx + 2, "error": "缺訂單編號/時間/地址"})
                continue

            pax = _i(r.get("乘客數量")) or 1
            wheelchair = _i(r.get("輪椅數量")) or 0
            type_req = _s(r.get("長照車型要求"))
            welfare = _is_welfare(type_req, wheelchair)
            p_lng, p_lat = _f(r.get("[上車]乘客地址經度")), _f(r.get("[上車]乘客地址緯度"))
            d_lng, d_lat = _f(r.get("[下車]乘客地址經度")), _f(r.get("[下車]乘客地址緯度"))
            p_city, p_town = _s(r.get("[上車]縣市")), _s(r.get("[上車]區市鄉鎮"))
            d_city, d_town = _s(r.get("[下車]縣市")), _s(r.get("[下車]區市鄉鎮"))
            plate = _s(r.get("車牌號碼"))
            driver_name = _s(r.get("駕駛姓名"))
            driver_phone = _s(r.get("駕駛手機"))
            fleet = _s(r.get("子車隊名稱"))  # 車行標記(集團統一派遣)

            # --- 自建車輛(by 車牌;共用車池,home_fleet 僅標記首見車行) ---
            vehicle = None
            if plate:
                vehicle = veh_cache.get(plate)
                if vehicle is None:
                    vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == plate))
                if vehicle is None:
                    vehicle = Vehicle(plate=plate, type="welfare" if welfare else "normal",
                                      seats=4, active=True, home_fleet=fleet,
                                      depot_lng=p_lng, depot_lat=p_lat)
                    db.add(vehicle)
                    db.flush()
                    report["vehicles_created"] += 1
                elif welfare and vehicle.type != "welfare":
                    vehicle.type = "welfare"  # 升級為福祉車
                veh_cache[plate] = vehicle

            # --- 自建司機(by 姓名) ---
            if driver_name:
                drv = drv_cache.get(driver_name)
                if drv is None:
                    drv = db.scalar(select(Driver).where(Driver.name == driver_name))
                if drv is None:
                    drv = Driver(name=driver_name, phone=driver_phone, home_fleet=fleet,
                                 vehicle_id=vehicle.id if vehicle else None, active=True)
                    db.add(drv)
                    db.flush()
                    report["drivers_created"] += 1
                drv_cache[driver_name] = drv

            # --- 灌地址簿(真實座標) ---
            _upsert_address(db, pickup_addr, p_lng, p_lat, p_city, p_town)
            _upsert_address(db, dropoff_addr, d_lng, d_lat, d_city, d_town)

            # --- upsert 訂單(by source_order_no) ---
            order = db.scalar(select(Order).where(Order.source_order_no == son))
            new = order is None
            if new:
                order = Order(source_order_no=son)
                db.add(order)
            order.fleet = fleet
            order.service_date = pickup_dt.date()
            order.pickup_time = pickup_dt
            order.passenger_name = _s(r.get("乘客姓名"))
            order.passenger_phone = _s(r.get("乘客電話"))
            order.pickup_address = pickup_addr
            order.dropoff_address = dropoff_addr
            order.pickup_lng, order.pickup_lat = p_lng, p_lat
            order.dropoff_lng, order.dropoff_lat = d_lng, d_lat
            order.pax = pax
            order.vehicle_type = "welfare" if welfare else "normal"
            order.need_wheelchair = wheelchair > 0
            order.allow_pool = _s(r.get("是否願意共乘")) == "True"
            order.note = _s(r.get("Memo")) or _s(r.get("附註(200字)"))
            order.status = STATUS_MAP.get(_s(r.get("CurrentStatus")) or "", "imported")
            order.assigned_vehicle_id = vehicle.id if vehicle else None
            db.flush()
            report["orders_created" if new else "orders_updated"] += 1

            # --- 人工派遣歷史(同編號先刪再寫,確保可重複匯入)---
            db.query(DispatchHistory).filter(DispatchHistory.source_order_no == son).delete()
            raw = {k: v for k, v in r.items() if k not in PII_DROP}
            db.add(DispatchHistory(
                source_order_no=son, fleet=fleet,
                service_date=pickup_dt.date(), pickup_time=pickup_dt,
                plate=plate, driver_name=driver_name, driver_phone=driver_phone,
                dispatcher=_s(r.get("派單人員")),
                pickup_city=p_city, pickup_town=p_town, dropoff_city=d_city, dropoff_town=d_town,
                pickup_address=pickup_addr, dropoff_address=dropoff_addr,
                pickup_lng=p_lng, pickup_lat=p_lat, dropoff_lng=d_lng, dropoff_lat=d_lat,
                vehicle_type_req=type_req, pax=pax, wheelchair_count=wheelchair,
                distance_m=_f(r.get("距離")), est_minutes=_f(r.get("預估分鐘數")),
                service_minutes=_f(r.get("服務分鐘")),
                fare_negotiated=_f(r.get("議價車資")), subsidy=_f(r.get("補助金額")),
                self_pay=_f(r.get("自付額")),
                status=_s(r.get("CurrentStatus")),
                order_created_at=_dt(r.get("訂單建立時間")), op_date=_dt(r.get("操作日期")),
                raw=raw,
            ))
            report["history_created"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append({"row": idx + 2, "error": str(e)})

    db.commit()
    return report
