#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從長照訂單 Excel 匯入訂單"""
import sys
sys.path.insert(0, "/app")

import xlrd, openpyxl
from datetime import datetime, timezone, timedelta
from app.db.session import SessionLocal
from app.models.order import Order
from app.models.vehicle import Vehicle
from sqlalchemy import select, delete

TW = timezone(timedelta(hours=8))
FILES = [
    ("/tmp/orders_0711.xls",  "xls"),
    ("/tmp/orders_0713.xlsx", "xlsx"),
]

# ── 欄位索引（兩份格式相同） ──
C = {
    "fleet":        1,
    "pickup_time":  5,
    "phone":        6,
    "name":         7,
    "pax":         14,
    "wheelchair":  15,
    "pool":        16,
    "note_driver": 34,   # 特別交待事項
    "pickup_addr": 18,
    "dropoff_addr":19,
    "pickup_lng":  48,
    "pickup_lat":  49,
    "dropoff_lng": 66,
    "dropoff_lat": 67,
    "car_type":    24,   # 長照車型要求
    "order_no":     3,
    "pool_consent":16,
}

def vtype(s):
    s = str(s).strip()
    return "welfare" if "福祉" in s else "normal"

def to_dt_xls(serial, datemode):
    t = xlrd.xldate_as_tuple(serial, datemode)
    return datetime(*t, tzinfo=TW)

def to_dt_str(s):
    if not s:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            return s.replace(tzinfo=TW)
        return s.astimezone(TW)
    s = str(s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TW)
        except ValueError:
            pass
    return None

def to_float(v):
    try:
        f = float(v)
        return f if f != 0.0 else None
    except (TypeError, ValueError):
        return None

def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0

def pool_bool(v):
    return str(v).strip().lower() in ("true", "1", "yes", "是")

def read_xls(path):
    wb = xlrd.open_workbook(path)
    sh = wb.sheet_by_index(0)
    rows = []
    for r in range(1, sh.nrows):
        v = [sh.cell_value(r, c) for c in range(sh.ncols)]
        if not v[C["name"]] and not v[C["pickup_addr"]]:
            continue
        try:
            pt = to_dt_xls(v[C["pickup_time"]], wb.datemode)
        except Exception:
            continue
        rows.append((v, pt))
    return rows

def read_xlsx(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = []
    for r, row in enumerate(ws.iter_rows(values_only=True)):
        if r == 0:
            continue
        v = list(row)
        if not v[C["name"]] and not v[C["pickup_addr"]]:
            continue
        pt = to_dt_str(v[C["pickup_time"]])
        if not pt:
            continue
        rows.append((v, pt))
    return rows

db = SessionLocal()

# 清除舊訂單
db.execute(delete(Order))
db.commit()

# 建車牌→vehicle_id 查找表
plate_map = {v.plate.upper(): v.id for v in db.scalars(select(Vehicle)).all() if v.plate}

imported = 0
skipped  = 0
seen_nos = set()

for path, fmt in FILES:
    rows = read_xls(path) if fmt == "xls" else read_xlsx(path)
    for v, pt in rows:
        order_no = str(v[C["order_no"]]).strip()
        if order_no in seen_nos:
            skipped += 1
            continue
        seen_nos.add(order_no)

        # 地址
        pickup_addr  = str(v[C["pickup_addr"]] or "").strip()
        dropoff_addr = str(v[C["dropoff_addr"]] or "").strip()
        if not pickup_addr or not dropoff_addr:
            skipped += 1
            continue

        # 座標
        plng = to_float(v[C["pickup_lng"]])
        plat = to_float(v[C["pickup_lat"]])
        dlng = to_float(v[C["dropoff_lng"]])
        dlat = to_float(v[C["dropoff_lat"]])

        o = Order(
            source_order_no = order_no,
            fleet           = str(v[C["fleet"]] or "").strip() or None,
            service_date    = pt.date(),
            pickup_time     = pt,
            pickup_window_min = 30,
            passenger_name  = str(v[C["name"]] or "").strip() or None,
            passenger_phone = str(v[C["phone"]] or "").strip() or None,
            pickup_address  = pickup_addr,
            pickup_lng      = plng,
            pickup_lat      = plat,
            dropoff_address = dropoff_addr,
            dropoff_lng     = dlng,
            dropoff_lat     = dlat,
            pax             = max(1, to_int(v[C["pax"]])),
            vehicle_type    = vtype(v[C["car_type"]]),
            need_wheelchair = to_int(v[C["wheelchair"]]) > 0,
            allow_pool      = pool_bool(v[C["pool_consent"]]),
            note            = str(v[C["note_driver"]] or "").strip() or None,
            status          = "imported",
        )
        db.add(o)
        imported += 1

db.commit()
print(f"完成：匯入 {imported} 筆，略過重複/無地址 {skipped} 筆")

# 摘要
from sqlalchemy import func as sqlfunc
for sd, cnt in db.execute(
    select(Order.service_date, sqlfunc.count()).group_by(Order.service_date).order_by(Order.service_date)
).all():
    print(f"  {sd}: {cnt} 筆")
