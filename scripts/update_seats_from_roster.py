#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, openpyxl
sys.path.insert(0, "/app")
from app.db.session import SessionLocal
from app.models.vehicle import Vehicle
from sqlalchemy import select

wb = openpyxl.load_workbook("/tmp/roster.xlsx", data_only=True)
db = SessionLocal()
plate_map = {v.plate.upper(): v for v in db.scalars(select(Vehicle)).all() if v.plate}

updated, skipped = 0, []
seen = set()

for sheet in ["0711", "0713"]:
    ws = wb[sheet]
    for r, row in enumerate(ws.iter_rows(values_only=True)):
        if r == 0:
            continue
        plate = str(row[4] or "").strip().upper()
        seats = row[8]
        wc    = row[9]
        if not plate or plate in seen:
            continue
        seen.add(plate)
        v = plate_map.get(plate)
        if not v:
            skipped.append(plate)
            continue
        if seats is not None:
            v.seats = int(float(seats))
        if wc is not None:
            v.wheelchair = int(float(wc))
        updated += 1

db.commit()
print(f"更新 {updated} 筆，跳過(查無車牌) {len(skipped)} 筆: {skipped}")

print("\n--- 更新後車輛座位 ---")
for v in db.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.plate)).all():
    print(f"  {v.plate:12s} seats={v.seats}  wheelchair={v.wheelchair}")
