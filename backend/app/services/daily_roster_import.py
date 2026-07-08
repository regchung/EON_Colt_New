"""每日出勤名冊上傳:從 XLS 設定當日出勤車輛/司機/班別時段。

欄位:駕駛姓名 子車隊名稱 車輛來源 車牌號碼 長照車型 乘客數 輪椅數 工作時段
工作時段格式:「8:00-18:00」或「8:00~18:00」

每次上傳指定日期:
  - 名冊內車輛 → shift_exception(available=True, 時段依工作時段欄)+ 更新 seats/wheelchair/vehicle_source
  - 名冊外 active 車輛 → shift_exception(available=False,當日停派)
  - 每一列有效司機+車輛 → driver_vehicle_assignment(當日配對,可重建)
  - 不動 suspended 主旗標(僅影響當日 shift_exception)
"""
from __future__ import annotations

import re
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.driver_vehicle_assignment import DriverVehicleAssignment
from app.models.shift import ShiftException
from app.models.vehicle import Vehicle
from app.services.fleet_import import _f, _i, _read_rows, _s


def _parse_time_range(raw: str | None) -> tuple[time | None, time | None]:
    """解析 '8:00-18:00' 或 '8:00~18:00' → (time, time);解析失敗回 (None, None)。"""
    if not raw:
        return None, None
    m = re.search(r"(\d{1,2}):(\d{2})\s*[-~–]\s*(\d{1,2}):(\d{2})", str(raw))
    if not m:
        return None, None
    try:
        sh, sm, eh, em = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return time(sh, sm), time(eh, em)
    except ValueError:
        return None, None


def import_daily_roster(db: Session, content: bytes, filename: str, service_date: date) -> dict:
    """上傳當日出勤名冊,寫入 shift_exception + driver_vehicle_assignment。"""
    rows = _read_rows(filename, content)

    rep = {
        "service_date": str(service_date),
        "rows": len(rows),
        "on_duty": 0,
        "off_duty": 0,
        "assignments": 0,
        "vehicles_updated": 0,
        "errors": [],
        "on_duty_list": [],
        "off_duty_list": [],
    }

    # --- 解析名冊,建立 plate→(司機,時段,specs) 映射 ---
    file_plates: dict[str, dict] = {}
    for idx, r in enumerate(rows):
        plate = _s(r.get("車牌號碼"))
        if not plate:
            rep["errors"].append({"row": idx + 2, "error": "缺車牌號碼,略過"})
            continue
        sh, se = _parse_time_range(_s(r.get("工作時段")))
        ltc = _s(r.get("長照車型"))
        wheelchair = _i(r.get("輪椅數")) or 0
        welfare = (ltc is not None and ltc != "小型") or wheelchair > 0
        file_plates[plate] = {
            "driver_name": _s(r.get("駕駛姓名")),
            "fleet": _s(r.get("子車隊名稱")),
            "vehicle_source": _s(r.get("車輛來源")),
            "seats": _i(r.get("乘客數")) or 4,
            "wheelchair": wheelchair,
            "welfare": welfare,
            "shift_start": sh,
            "shift_end": se,
        }

    # --- 清除該日舊資料(冪等) ---
    old_exc = db.scalars(select(ShiftException).where(ShiftException.ex_date == service_date)).all()
    for e in old_exc:
        db.delete(e)

    old_dva = db.scalars(
        select(DriverVehicleAssignment).where(DriverVehicleAssignment.service_date == service_date)
    ).all()
    for a in old_dva:
        db.delete(a)
    db.flush()

    # --- 所有 active 車輛寫 shift_exception ---
    all_vehicles = db.scalars(select(Vehicle).where(Vehicle.active.is_(True))).all()
    for v in all_vehicles:
        plate = _s(v.plate)
        if plate in file_plates:
            spec = file_plates[plate]
            # 更新車輛規格
            if spec["fleet"]:
                v.home_fleet = spec["fleet"]
            if spec["vehicle_source"]:
                v.vehicle_source = spec["vehicle_source"]
            v.seats = spec["seats"]
            v.wheelchair = spec["wheelchair"]
            v.type = "welfare" if spec["welfare"] else "normal"
            rep["vehicles_updated"] += 1

            exc = ShiftException(
                vehicle_id=v.id,
                ex_date=service_date,
                available=True,
                shift_start=spec["shift_start"],
                shift_end=spec["shift_end"],
                reason="每日名冊上傳",
            )
            rep["on_duty"] += 1
            rep["on_duty_list"].append(plate)
        else:
            exc = ShiftException(
                vehicle_id=v.id,
                ex_date=service_date,
                available=False,
                reason="每日名冊:未出勤",
            )
            rep["off_duty"] += 1
            rep["off_duty_list"].append(plate)
        db.add(exc)

    db.flush()

    # --- driver_vehicle_assignment ---
    for plate, spec in file_plates.items():
        driver_name = spec["driver_name"]
        if not driver_name:
            continue
        vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == plate))
        if vehicle is None:
            # 名冊中有但 DB 沒有此車 → 建立
            vehicle = Vehicle(
                plate=plate,
                active=True,
                home_fleet=spec["fleet"],
                vehicle_source=spec["vehicle_source"],
                seats=spec["seats"],
                wheelchair=spec["wheelchair"],
                type="welfare" if spec["welfare"] else "normal",
            )
            db.add(vehicle)
            db.flush()
            # 補 shift_exception
            db.add(ShiftException(
                vehicle_id=vehicle.id,
                ex_date=service_date,
                available=True,
                shift_start=spec["shift_start"],
                shift_end=spec["shift_end"],
                reason="每日名冊上傳(新車)",
            ))
            db.flush()

        driver = db.scalar(select(Driver).where(Driver.name == driver_name))
        if driver is None:
            driver = Driver(name=driver_name, active=True, home_fleet=spec["fleet"])
            db.add(driver)
            db.flush()

        dva = DriverVehicleAssignment(
            service_date=service_date,
            driver_id=driver.id,
            vehicle_id=vehicle.id,
            note="每日名冊上傳",
        )
        db.add(dva)
        rep["assignments"] += 1

    db.commit()
    return rep
