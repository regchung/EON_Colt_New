"""大豐派遣班表 Excel 匯入器。

欄位對應：
  日期(民國整數)→service_date、個案名→passenger_name、連絡電話→passenger_phone
  出發地→pickup_address、目的地→dropoff_address、客上→pickup_time
  地區→customer_region、性質→order_nature、1.補助2.自費→payment_type
  身分資格→eligibility、車型/配件→vehicle_type
  Unnamed:3(訂車類型)+備註+派遣備注→note
  里程→mileage、車資→fare、陪同金額→companion_fee
  自付金額→self_pay_amount、補助餘額→subsidy_balance
  派遣狀態→status(派遣成功+有車號=scheduled, 其餘=imported)
  車號→反查 vehicles 表取 assigned_vehicle_id
"""
from __future__ import annotations

import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select, delete

from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services.geocode import geocode

TW = ZoneInfo("Asia/Taipei")

VEHICLE_TYPE_MAP = {"輪": "welfare", "一般": "normal", "小車": "normal"}
PAYMENT_MAP = {1: "subsidy", 2: "self", "1": "subsidy", "2": "self",
               1.0: "subsidy", 2.0: "self"}


def _roc_to_date(val) -> datetime.date | None:
    try:
        s = str(int(val)).zfill(7)
        y = int(s[:3]) + 1911
        m = int(s[3:5])
        d = int(s[5:7])
        return datetime.date(y, m, d)
    except Exception:
        return None


def _parse_time(val) -> datetime.time | None:
    if isinstance(val, datetime.time):
        return val
    if isinstance(val, datetime.datetime):
        return val.time()
    if isinstance(val, str):
        try:
            parts = val.strip().replace(";", ":").split(":")
            return datetime.time(int(parts[0]), int(parts[1]))
        except Exception:
            return None
    return None


def _safe_int(val) -> int | None:
    try:
        f = float(val)
        return None if pd.isna(f) else int(f)
    except Exception:
        return None


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if pd.isna(f) else round(f, 2)
    except Exception:
        return None


def _safe_str(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    s = str(val).strip()
    return s if s else None


def _split_address(val) -> tuple[str | None, str | None]:
    """地址欄可能含換行或括號補充說明，拆成 (主地址, 補充備注)。
    例：'板橋區民生路三段315號\n(社區大門在長江路一段415號上下車)'
    → ('板橋區民生路三段315號', '(社區大門在長江路一段415號上下車)')
    """
    s = _safe_str(val)
    if not s:
        return None, None
    # 換行切分
    lines = [l.strip() for l in s.splitlines() if l.strip()]
    if len(lines) >= 2:
        return lines[0], " ".join(lines[1:])
    # 無換行但有括號補充（地址後接空格+括號）
    import re
    m = re.match(r'^(.+?)\s+(\(.*\))$', lines[0])
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return lines[0], None


def _build_note(*parts) -> str | None:
    """合併多個欄位到 note，None/空值略過。"""
    pieces = []
    labels = ["訂車類型", None, "派遣備注"]
    for label, v in zip(labels, parts):
        s = _safe_str(v)
        if s:
            pieces.append(f"[{s}]" if label == "訂車類型" else
                          f"派遣備注:{s}" if label == "派遣備注" else s)
    return " ".join(pieces) if pieces else None


def _plate_map(db: Session) -> dict[str, int]:
    rows = db.execute(select(Vehicle.id, Vehicle.plate)).all()
    return {(p or "").replace("-", "").replace(" ", "").upper(): vid
            for vid, p in rows if p}


def import_excel(db: Session, file_bytes: bytes,
                 replace_date: bool = False) -> dict:
    """
    匯入大豐班表 Excel。
    replace_date=True：先刪除相同服務日期的既有訂單，再匯入（冪等）。
    """
    # 讀取所有 sheet 並合併（支援每日分頁格式）
    xl = pd.ExcelFile(BytesIO(file_bytes))
    frames = []
    for sheet in xl.sheet_names:
        _df = xl.parse(sheet, header=0)
        if not _df.empty:
            frames.append(_df)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # 標準化欄位名稱（部分月份欄位標頭為空格/None，改用位置索引回填）
    STD_COLS = {
        0: "日期", 1: "派遣狀態", 2: "派遣備注", 3: "客戶", 4: "個案名",
        5: "身分證字號", 6: "連絡電話", 7: "1.補助 2.自費", 8: "性質",
        9: "客上", 10: "地區", 11: "出發地", 12: "目的地", 13: "客下",
        14: "里程", 15: "車資", 16: "陪同金額", 17: "自付金額",
        18: "車號", 19: "司機", 20: "車型/配件", 21: "補助餘額",
        22: "身分資格", 23: "備註", 24: "填單人", 25: "等級",
    }
    new_cols = []
    for i, c in enumerate(df.columns):
        s = str(c).strip()
        # 空白或 None 或 Unnamed → 用標準名稱替補
        if not s or s.startswith("Unnamed") or s in ("None", "nan"):
            s = STD_COLS.get(i, f"col_{i}")
        new_cols.append(s)
    df.columns = new_cols

    # --- 第一輪：掃出所有服務日期 ---
    dates_seen: set[datetime.date] = set()
    rows_parsed = []
    errors: list[str] = []
    skipped = 0

    pmap = _plate_map(db)

    for idx, row in df.iterrows():
        lineno = idx + 2
        raw_date = row.get("日期")
        # 日期為空/NaN → 空白列，靜默跳過
        if raw_date is None or (isinstance(raw_date, float) and pd.isna(raw_date)):
            continue
        svc_date = _roc_to_date(raw_date)
        if svc_date is None:
            errors.append(f"第{lineno}列：日期無法解析({raw_date})")
            skipped += 1
            continue

        t = _parse_time(row.get("客上"))
        if t is None:
            errors.append(f"第{lineno}列：客上時間無法解析({row.get('客上')})")
            skipped += 1
            continue

        pickup_addr, pickup_note = _split_address(row.get("出發地"))
        dropoff_addr, dropoff_note = _split_address(row.get("目的地"))
        if not pickup_addr or not dropoff_addr:
            errors.append(f"第{lineno}列：出發地或目的地為空")
            skipped += 1
            continue

        dates_seen.add(svc_date)
        rows_parsed.append((svc_date, t, pickup_addr, dropoff_addr, pickup_note, dropoff_note, row))

    # --- replace_date：先刪舊單 ---
    if replace_date and dates_seen:
        db.execute(delete(Order).where(Order.service_date.in_(list(dates_seen))))
        db.flush()

    # --- 第二輪：新增訂單 ---
    imported = 0
    geocoded = 0
    for svc_date, t, pickup_addr, dropoff_addr, pickup_note, dropoff_note, row in rows_parsed:
        pickup_dt = datetime.datetime.combine(svc_date, t).replace(tzinfo=TW)

        vt_raw = _safe_str(row.get("車型/配件")) or "一般"
        vehicle_type = VEHICLE_TYPE_MAP.get(vt_raw, "normal")

        payment_raw = row.get("1.補助 2.自費")
        payment_type = PAYMENT_MAP.get(payment_raw, "subsidy")

        dispatch_ok = _safe_str(row.get("派遣狀態")) == "派遣成功"
        plate_raw = _safe_str(row.get("車號"))
        plate_key = (plate_raw or "").replace("-", "").replace(" ", "").upper()
        assigned_vid = pmap.get(plate_key) if plate_key else None
        status = "scheduled" if (dispatch_ok and assigned_vid) else "imported"

        addr_extra = " ".join(filter(None, [pickup_note, dropoff_note]))
        note = _build_note(row.get("Unnamed: 3"), row.get("備註"), row.get("派遣備注"))
        if addr_extra:
            note = (note + " " + addr_extra).strip() if note else addr_extra

        subsidy_col = "補助餘額 " if "補助餘額 " in df.columns else "補助餘額"

        # 客下車時間
        t_off = _parse_time(row.get("客下"))
        dropoff_dt = datetime.datetime.combine(svc_date, t_off).replace(tzinfo=TW) if t_off else None

        # 預約方式（客戶欄，標準化後統一為「客戶」）
        booking_src = _safe_str(row.get("客戶"))

        o = Order(
            service_date=svc_date,
            fleet="大豐",           # 預設公司/子車隊
            pickup_time=pickup_dt,
            pickup_window_min=30,
            passenger_name=_safe_str(row.get("個案名")),
            passenger_phone=_safe_str(row.get("連絡電話")),
            pickup_address=pickup_addr,
            dropoff_address=dropoff_addr,
            pax=1,
            vehicle_type=vehicle_type,
            need_wheelchair=(vehicle_type == "welfare"),
            allow_pool=False,   # 原則不共乘，需個別徵詢同意
            payment_type=payment_type,
            order_nature=_safe_str(row.get("性質")),
            customer_region=_safe_str(row.get("地區")),
            eligibility=_safe_str(row.get("身分資格")),
            note=note,
            mileage=_safe_float(row.get("里程")),
            fare=_safe_int(row.get("車資")),
            companion_fee=_safe_int(row.get("陪同金額")),
            self_pay_amount=_safe_int(row.get("自付金額")),
            subsidy_balance=_safe_str(row.get(subsidy_col)),
            status=status,
            assigned_vehicle_id=assigned_vid,
            # 擴充欄位
            booking_source=booking_src,
            id_number=_safe_str(row.get("身分證字號")),
            dropoff_time=dropoff_dt,
            assigned_plate=plate_raw,
            driver_name=_safe_str(row.get("司機")),
            operator=_safe_str(row.get("填單人")),
        )
        db.add(o)
        db.flush()  # 取得 o.id 後再做地理編碼

        # 地理編碼：先查 DB 快取，沒有才打外部 API，結果回寫地址表
        pk = geocode(db, pickup_addr)
        if pk.found:
            o.pickup_lng, o.pickup_lat = pk.lng, pk.lat
        dp = geocode(db, dropoff_addr)
        if dp.found:
            o.dropoff_lng, o.dropoff_lat = dp.lng, dp.lat
        if pk.found and dp.found:
            geocoded += 1

        imported += 1

    db.commit()

    return {
        "imported": imported,
        "geocoded": geocoded,
        "skipped": skipped,
        "errors": errors[:50],
        "dates": sorted(d.isoformat() for d in dates_seen),
        "date_count": len(dates_seen),
    }
