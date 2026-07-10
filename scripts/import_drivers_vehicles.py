#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從 長照司機工作資料管理(全部司機).xls 匯入司機與車輛"""
import sys, xlrd
sys.path.insert(0, "/app")

from app.db.session import SessionLocal
from app.models.vehicle import Vehicle
from app.models.driver import Driver
from sqlalchemy import select, delete

XLS_PATH = "/tmp/drivers.xls"

# 長照車型 → vehicle.type
def vtype(s):
    return "welfare" if "福祉" in s else "normal"

# 子車隊 → home_fleet（取主要所屬）
def fleet(s):
    s = s.strip()
    if not s:
        return None
    # 神同行優先
    if "神同行" in s:
        return "神同行"
    if "樂格適" in s:
        return "樂格適"
    # 斜線分隔取第一個
    return s.split("/")[0].strip()

wb = xlrd.open_workbook(XLS_PATH)
sh = wb.sheet_by_index(0)

rows = []
for r in range(1, sh.nrows):
    vals = [sh.cell_value(r, c) for c in range(sh.ncols)]
    name     = str(vals[0]).strip()
    fleet_s  = str(vals[1]).strip()
    source   = str(vals[2]).strip()
    plate    = str(vals[3]).strip().upper()
    car_type = str(vals[6]).strip()   # 長照車型
    seats    = int(vals[7]) if vals[7] else 4
    wheelchair = int(vals[8]) if vals[8] else 0
    note     = str(vals[9]).strip() if len(vals) > 9 else ""
    rows.append(dict(name=name, fleet=fleet_s, source=source, plate=plate,
                     car_type=car_type, seats=seats, wheelchair=wheelchair, note=note))

db = SessionLocal()

# 清空舊資料
db.execute(delete(Driver))
db.execute(delete(Vehicle))
db.commit()

created_v = 0
created_d = 0
skipped   = []

for row in rows:
    plate = row["plate"]
    if not plate:
        skipped.append(f"(無車牌) {row['name'] or '備用車'}")
        continue

    # 備用車（無司機）：只建車輛
    suspended = "暫不排" in row["note"]
    active    = "備用" not in row["note"]

    v = Vehicle(
        plate=plate,
        type=vtype(row["car_type"]),
        seats=row["seats"],
        wheelchair=row["wheelchair"],
        home_fleet=fleet(row["fleet"]),
        vehicle_source=row["source"] or None,
        active=active,
        suspended=suspended,
    )
    db.add(v)
    db.flush()   # 取得 v.id
    created_v += 1

    if row["name"]:
        d = Driver(
            name=row["name"],
            home_fleet=fleet(row["fleet"]),
            vehicle_id=v.id,
            active=True,
            suspended=suspended,
        )
        db.add(d)
        created_d += 1

db.commit()

print(f"完成：車輛 {created_v} 筆，司機 {created_d} 筆")
if skipped:
    print(f"跳過（無車牌）：{skipped}")

# 驗證
print("\n--- 司機清單 ---")
for d in db.scalars(select(Driver).order_by(Driver.home_fleet, Driver.name)).all():
    v = db.get(Vehicle, d.vehicle_id) if d.vehicle_id else None
    flag = " [停派]" if d.suspended else ""
    print(f"  {d.home_fleet or '?':8s} {d.name:8s} → {v.plate if v else '-'}{flag}")

print("\n--- 備用/無司機車輛 ---")
for v in db.scalars(select(Vehicle)).all():
    has_driver = db.scalar(select(Driver).where(Driver.vehicle_id == v.id))
    if not has_driver:
        print(f"  {v.plate} ({v.type}) active={v.active}")
