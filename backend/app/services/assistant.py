"""調度員 AI 助理:對話式 + Claude tool-use。

定位(v1,唯讀建議):Claude 可呼叫「查單 / 當日出勤 / 營運統計 / 需求預測」等唯讀工具,
以真實資料為依據回答調度員問題並給建議;實際寫入動作(排班/指派)仍由既有 UI 按鈕執行,
助理只「建議」。日後再加「確認→寫入」的受控寫入工具(見 BACKLOG)。

無 ANTHROPIC_API_KEY 時回傳提示(優雅降級)。
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import forecast as forecast_svc
from app.services import roster as roster_svc

_API_URL = "https://api.anthropic.com/v1/messages"
_HEADERS = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
_MAX_ROUNDS = 5   # tool-use 迴圈上限,避免無限往返

_SYSTEM = (
    "你是長照車隊的智慧調度助理。可用工具查詢真實營運資料(訂單、當日出勤車、統計、需求預測),"
    "請先查資料再回答,用繁體中文、條列、阿拉伯數字、簡潔專業。"
    "你只負責『查詢與建議』,不執行排班或指派;若需要排班,請建議使用者到對應頁面按『一鍵排班』。"
)

# --- Claude tools 定義(唯讀)---
TOOLS: list[dict] = [
    {
        "name": "query_orders",
        "description": "查詢訂單。可依服務日期、狀態、乘客姓名過濾,回傳摘要清單。",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_date": {"type": "string", "description": "YYYY-MM-DD"},
                "status": {"type": "string", "enum": ["imported", "scheduled", "ongoing", "done", "canceled"]},
                "passenger": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "dispatch_overview",
        "description": "某日營運概況:各狀態訂單數、已/未地理編碼、當日出勤車數。",
        "input_schema": {
            "type": "object",
            "properties": {"service_date": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["service_date"],
        },
    },
    {
        "name": "vehicles_on_duty",
        "description": "某日依班表出勤的車輛清單(車牌、班別時段)。",
        "input_schema": {
            "type": "object",
            "properties": {"service_date": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["service_date"],
        },
    },
    {
        "name": "demand_forecast",
        "description": "需求預測(weekday 基線):各星期平均趟次與建議排車數。可指定車行。",
        "input_schema": {
            "type": "object",
            "properties": {"fleet": {"type": "string"}, "lookback_weeks": {"type": "integer", "default": 12}},
        },
    },
]


# --- 工具執行(皆唯讀)---
def _t_query_orders(db: Session, service_date=None, status=None, passenger=None, limit=20) -> dict:
    q = select(Order)
    if service_date:
        q = q.where(Order.service_date == date.fromisoformat(service_date))
    if status:
        q = q.where(Order.status == status)
    if passenger:
        q = q.where(Order.passenger_name.ilike(f"%{passenger}%"))
    rows = list(db.scalars(q.order_by(Order.service_date, Order.pickup_time).limit(min(int(limit or 20), 100))).all())
    return {"count": len(rows), "orders": [
        {"id": o.id, "service_date": o.service_date.isoformat(),
         "pickup_time": o.pickup_time.strftime("%H:%M") if o.pickup_time else None,
         "passenger": o.passenger_name, "pickup": o.pickup_address, "dropoff": o.dropoff_address,
         "vehicle_type": o.vehicle_type, "pax": o.pax, "status": o.status,
         "geocoded": o.pickup_lng is not None and o.dropoff_lng is not None}
        for o in rows]}


def _t_dispatch_overview(db: Session, service_date: str) -> dict:
    sd = date.fromisoformat(service_date)
    base = select(Order.status, func.count()).where(Order.service_date == sd).group_by(Order.status)
    by_status = {s: c for s, c in db.execute(base).all()}
    geocoded = db.scalar(select(func.count()).select_from(Order).where(
        Order.service_date == sd, Order.pickup_lng.is_not(None), Order.dropoff_lng.is_not(None))) or 0
    total = sum(by_status.values())
    on_duty = len(roster_svc.available_vehicles(db, sd))
    return {"service_date": service_date, "total_orders": total, "by_status": by_status,
            "geocoded": geocoded, "ungeocoded": total - geocoded, "vehicles_on_duty": on_duty}


def _t_vehicles_on_duty(db: Session, service_date: str) -> dict:
    sd = date.fromisoformat(service_date)
    duty = roster_svc.available_vehicles(db, sd)
    plates = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(duty.keys()))).all()} if duty else {}
    out = []
    for vid, (s, e) in sorted(duty.items()):
        v = plates.get(vid)
        out.append({"plate": v.plate if v else f"#{vid}", "type": v.type if v else None,
                    "shift_start_sec": s, "shift_end_sec": e})
    return {"service_date": service_date, "count": len(out), "vehicles": out}


def _t_demand_forecast(db: Session, fleet=None, lookback_weeks=12) -> dict:
    prof = forecast_svc.weekday_profile(db, fleet, int(lookback_weeks or 12))
    return {"fleet": fleet, "last_date": prof.get("last_date"), "weekdays": prof.get("weekdays", [])}


_EXECUTORS = {
    "query_orders": _t_query_orders,
    "dispatch_overview": _t_dispatch_overview,
    "vehicles_on_duty": _t_vehicles_on_duty,
    "demand_forecast": _t_demand_forecast,
}


def _run_tool(db: Session, name: str, args: dict) -> dict:
    fn = _EXECUTORS.get(name)
    if fn is None:
        return {"error": f"未知工具:{name}"}
    try:
        return fn(db, **(args or {}))
    except Exception as e:  # noqa: BLE001 — 工具錯誤回給模型,讓它改問法
        return {"error": str(e)}


def _post(body: dict) -> dict:
    headers = {**_HEADERS, "x-api-key": settings.ANTHROPIC_API_KEY}
    resp = httpx.post(_API_URL, json=body, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def chat(db: Session, messages: list[dict]) -> dict:
    """跑 tool-use 迴圈,回傳 {reply, tool_trace}。messages 為 [{role, content(str)}]。"""
    if not settings.ANTHROPIC_API_KEY:
        return {"reply": "（未設定 ANTHROPIC_API_KEY,AI 助理停用)", "tool_trace": []}

    # 轉成 Anthropic messages 格式(使用者/助理純文字)
    convo: list[dict[str, Any]] = [{"role": m["role"], "content": m["content"]} for m in messages]
    trace: list[dict] = []

    for _ in range(_MAX_ROUNDS):
        data = _post({
            "model": settings.AI_DISPATCH_MODEL,
            "max_tokens": 1500,
            "system": _SYSTEM,
            "tools": TOOLS,
            "messages": convo,
        })
        blocks = data.get("content", [])
        if data.get("stop_reason") == "tool_use":
            convo.append({"role": "assistant", "content": blocks})
            results = []
            for b in blocks:
                if b.get("type") == "tool_use":
                    out = _run_tool(db, b["name"], b.get("input") or {})
                    trace.append({"tool": b["name"], "input": b.get("input"), "output": out})
                    results.append({"type": "tool_result", "tool_use_id": b["id"],
                                    "content": json.dumps(out, ensure_ascii=False)})
            convo.append({"role": "user", "content": results})
            continue
        # end_turn:組合文字回覆
        reply = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return {"reply": reply.strip(), "tool_trace": trace}

    return {"reply": "(查詢往返次數過多,請縮小問題範圍再試)", "tool_trace": trace}
