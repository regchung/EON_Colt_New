#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從每日司機出勤.xlsx 匯入 ShiftException（單日出勤名冊）"""
import sys, re, openpyxl
sys.path.insert(0, "/app")

from datetime import date, time
from app.db.session import SessionLocal
from app.models.driver import Driver
from app.models.shift import ShiftException
from app.models.vehicle import Vehicle
from sqlalchemy import select, delete

XLS_PATH = "/tmp/roster.xlsx"

def parse_time_range(note: str):
    """從備註解析 HH:MM-HH:MM，回傳 (time|None, time|None)"""
    m = re.search(r'(\d{1,2}):(\d{2})\s*[-~～]\s*(\d{1,2}):(\d{2})', note or '')
    if m:
        h1, m1, h2, m2 = int(m[1]), int(m[2]), int(m[3]), int(m[4])
        return time(h1, m1), time(h2, m2)
    return None, None

def sheet_to_date(sheet_name: str) -> date:
    """0711 → 2026-07-11"""
    return date(2026, int(sheet_name[:2]), int(sheet_name[2:]))

wb = openpyxl.load_workbook(XLS_PATH, data_only=True)
db = SessionLocal()

# 車牌 → vehicle_id
plate_map = {v.plate.upper(): v.id for v in db.scalars(select(Vehicle)).all() if v.plate}
name_map  = {d.name: d.id for d in db.scalars(select(Driver)).all()}

created = 0
skipped = []

for sheet_name in ['0711', '0713']:
    if sheet_name not in wb.sheetnames:
        continue
    ws = wb[sheet_name]
    svc_date = sheet_to_date(sheet_name)

    # 清除該日既有例外
    db.execute(delete(ShiftException).where(ShiftException.ex_date == svc_date))
    db.commit()

    for r, row in enumerate(ws.iter_rows(values_only=True)):
        if r == 0: continue          # 跳標頭
        driver_name = str(row[1] or '').strip()
        plate       = str(row[4] or '').strip().upper()
        note        = str(row[10] or '').strip() if len(row) > 10 else ''

        if not driver_name or not plate:
            continue

        vid = plate_map.get(plate)
        if vid is None:
            skipped.append(f"{svc_date} {driver_name} {plate}（車牌未建檔）")
            continue

        s_start, s_end = parse_time_range(note)
        did = name_map.get(driver_name)
        db.add(ShiftException(
            vehicle_id  = vid,
            ex_date     = svc_date,
            available   = True,
            shift_start = s_start,
            shift_end   = s_end,
            driver_id   = did,
            reason      = f"出勤名冊匯入 司機:{driver_name}" + (f" 備註:{note}" if note else ""),
        ))
        created += 1

db.commit()
print(f"完成：寫入 {created} 筆 ShiftException")

# 摘要
for sd in [date(2026,7,11), date(2026,7,13)]:
    excs = db.scalars(select(ShiftException).where(ShiftException.ex_date == sd)).all()
    print(f"\n  {sd}（{len(excs)} 台出勤）：")
    for e in excs:
        v = db.get(Vehicle, e.vehicle_id)
        ts = f" {e.shift_start.strftime('%H:%M')}-{e.shift_end.strftime('%H:%M')}" if e.shift_start else ""
        print(f"    {v.plate if v else '?'}{ts}  {e.reason}")

if skipped:
    print(f"\n跳過 {len(skipped)} 筆：")
    for s in skipped:
        print(f"  {s}")
