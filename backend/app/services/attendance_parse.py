"""自然語言出勤異動解析:把行控貼的文字 → 結構化班表異動。

例:
  「休3人:朱正元、張啟明、温智祥」 → 3 筆 休假
  「梁銘漢週一8:00-11:00不排,11:00可以接」 → 晚到,start_time=11:00
解析後對應到 ShiftException(由 driver_resolve 對應到車輛)。需 ANTHROPIC_API_KEY。
"""
from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy.orm import Session

from app.services import ai_dispatch, driver_resolve

_SYSTEM = (
    "你是長照車隊的出勤異動解析器。使用者會貼出當日司機出勤調整的文字,"
    "請只輸出 JSON 陣列,不要任何說明或 markdown 圍欄。"
)

# status → (available, 使用 start, 使用 end)
_STATUS = {"休假": False, "晚到": True, "早退": True, "加班": True, "正常": True}


def _prompt(text: str) -> str:
    return (
        "請把以下出勤異動文字解析成 JSON 陣列,每筆物件:\n"
        '- driver: 司機姓名(字串)\n'
        '- status: "休假"(整天不出勤) | "晚到"(較晚才出勤) | "早退"(提早收車) | '
        '"加班"(額外出勤) | "正常"\n'
        '- start_time: "HH:MM" 或 null(晚到=可開始接送的時間)\n'
        '- end_time: "HH:MM" 或 null(早退=最後可接送的時間)\n'
        '- reason: 字串或 null\n'
        "規則:『休X人』後面列的名字都是休假;『8:00-11:00不排,11:00可接』代表晚到 start_time=11:00。\n"
        f"只輸出 JSON 陣列。文字如下:\n---\n{text}\n---"
    )


def _strip(raw: str) -> str:
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE).strip()
    i, j = s.find("["), s.rfind("]")
    return s[i:j + 1] if i != -1 and j != -1 and j > i else s


def _norm_time(v) -> str | None:
    if not v:
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", str(v))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def parse(db: Session, text: str, service_date: date) -> dict:
    """回傳預覽:解析結果 + 對應車輛 + 是否可套用(司機有車)。"""
    if not text.strip():
        return {"items": [], "errors": ["請輸入出勤異動文字"]}
    raw = ai_dispatch._call_claude(_prompt(text), system=_SYSTEM, max_tokens=2048, timeout=60)
    try:
        data = json.loads(_strip(raw))
    except json.JSONDecodeError as e:
        return {"items": [], "errors": [f"AI 回傳非有效 JSON:{e}"], "raw": raw}
    if isinstance(data, dict):
        data = [data]

    items, errors = [], []
    for rec in data if isinstance(data, list) else []:
        if not isinstance(rec, dict) or not rec.get("driver"):
            continue
        name = str(rec["driver"]).strip()
        status = str(rec.get("status") or "休假").strip()
        available = _STATUS.get(status, False)
        start = _norm_time(rec.get("start_time")) if status in ("晚到", "加班") else None
        end = _norm_time(rec.get("end_time")) if status == "早退" else None
        veh = driver_resolve.resolve(db, name, service_date)
        items.append({
            "driver": name, "status": status, "available": available,
            "shift_start": start, "shift_end": end, "reason": rec.get("reason"),
            "vehicle_id": veh.id if veh else None, "plate": veh.plate if veh else None,
            "applicable": veh is not None,
        })
        if veh is None:
            errors.append(f"{name}:系統查無對應車輛,無法套用(請到「司機車輛」建檔)")
    return {"service_date": service_date.isoformat(), "items": items, "errors": errors}
