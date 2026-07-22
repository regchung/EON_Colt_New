#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從長照司機工作資料管理.xls 更新車輛起訖座標與車隊歸屬"""
import sys, xlrd
sys.path.insert(0, "/app")

from app.db.session import SessionLocal
from app.models.vehicle import Vehicle
from app.models.driver import Driver
from sqlalchemy import select

XLS = "/tmp/vehicles_new.xls"

def fleet(s):
    s = str(s).strip()
    if not s: return None
    if "神同行" in s: return "神同行"
    if "樂格適" in s: return "樂格適"
    if "基隆" in s: return "基隆"
    return s.split("/")[0].strip()

def vtype(s):
    return "welfare" if "福祉" in str(s) else "normal"

def flt(v):
    try:
        f = float(v)
        return f if f else None
    except (TypeError, ValueError):
        return None

wb = xlrd.open_workbook(XLS)
sh = wb.sheet_by_index(0)

db = SessionLocal()
plate_to_veh = {v.plate.upper(): v for v in db.scalars(select(Vehicle)).all() if v.plate}
plate_to_drv = {
    v.plate.upper(): db.get(Driver, d_id)
    for v in db.scalars(select(Vehicle)).all() if v.plate
    for (d_id,) in db.execute(
        select(Driver.id).where(Driver.vehicle_id == v.id)).all()
}

updated = 0
new_veh = 0
new_drv = 0
skipped = []

for r in range(1, sh.nrows):
    row = [sh.cell_value(r, c) for c in range(sh.ncols)]
    drv_name  = str(row[0]).strip()
    fleet_str = str(row[1]).strip()
    plate     = str(row[2]).strip().upper()
    car_type  = str(row[5]).strip()
    slng = flt(row[6]); slat = flt(row[7])
    elng = flt(row[8]); elat = flt(row[9])
    seats     = int(float(row[11])) if row[11] else 4
    wheelchair = int(float(row[12])) if row[12] else 0

    if not plate:
        skipped.append(f"第{r+1}列 無車牌")
        continue

    hf = fleet(fleet_str)

    # 更新或新建車輛
    v = plate_to_veh.get(plate)
    if v:
        v.start_lng    = slng
        v.start_lat    = slat
        v.end_lng      = elng
        v.end_lat      = elat
        v.home_fleet   = hf
        v.type         = vtype(car_type)
        v.seats        = seats
        v.wheelchair   = wheelchair
        updated += 1
    else:
        v = Vehicle(plate=plate, type=vtype(car_type), seats=seats,
                    wheelchair=wheelchair, home_fleet=hf,
                    start_lng=slng, start_lat=slat,
                    end_lng=elng, end_lat=elat, active=True)
        db.add(v)
        db.flush()
        plate_to_veh[plate] = v
        new_veh += 1

    # 更新司機的 home_fleet
    d = plate_to_drv.get(plate)
    if d:
        d.home_fleet = hf

db.commit()
print(f"完成：更新 {updated} 筆，新增車輛 {new_veh} 筆")

# 驗證
print("\n--- 出車起點確認 ---")
for v in db.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.home_fleet, Vehicle.plate)).all():
    has = "✓" if v.start_lng else "✗"
    print(f"  {has} {v.home_fleet or '?':8s} {v.plate:12s} start=({v.start_lng},{v.start_lat}) end=({v.end_lng},{v.end_lat})")
