"""AI 派遣輔助：呼叫 Claude API 分析排班結果，提供人類可讀的摘要與建議。

功能：
1. analyze_dispatch   — 排班後分析 unassigned 原因 + 產出每日摘要
2. evaluate_insertion — 臨時插單時評估插入哪台車影響最小
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings

_API_URL = "https://api.anthropic.com/v1/messages"
_HEADERS = {
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}


def _call_claude(prompt: str, system: str = "", max_tokens: int = 1024,
                 timeout: float = 30) -> str:
    """同步呼叫 Claude API，回傳文字。無 API key 時回傳提示訊息。"""
    if not settings.ANTHROPIC_API_KEY:
        return "（未設定 ANTHROPIC_API_KEY，AI 功能停用）"

    body: dict[str, Any] = {
        "model": settings.AI_DISPATCH_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    headers = {**_HEADERS, "x-api-key": settings.ANTHROPIC_API_KEY}
    resp = httpx.post(_API_URL, json=body, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


_SYSTEM_DISPATCH = (
    "你是一位專業的車隊派遣顧問。"
    "請用繁體中文回答，語氣簡潔專業，條列式呈現重點。"
    "數字請用阿拉伯數字，避免不必要的廢話。"
)


def analyze_dispatch(dispatch_result: dict) -> str:
    """排班完成後，分析結果並給出摘要與建議。"""
    unassigned = dispatch_result.get("unassigned", [])
    vehicles_used = dispatch_result.get("vehicles_used", 0)
    assigned = dispatch_result.get("assigned", 0)
    total = dispatch_result.get("orders_total", 0)
    skipped = dispatch_result.get("skipped_no_coords", [])
    routes = dispatch_result.get("routes", {})
    total_sec = dispatch_result.get("total_duration_sec", 0)
    service_date = dispatch_result.get("service_date", "")

    # 整理每車派遣概況（只取前 10 台避免 token 過長）
    vehicle_summaries = []
    for vid, stops in list(routes.items())[:10]:
        vehicle_summaries.append(
            f"  車輛 {vid}：{len(stops)} 趟（"
            + "、".join(f"#{s['order_id']} {s['type']} {s['eta']}" for s in stops[:4])
            + ("…" if len(stops) > 4 else "")
            + "）"
        )

    prompt = f"""以下是 {service_date} 的自動排班結果，請提供：
1. 一段 2-3 句的每日派遣摘要（給調度員看）
2. 若有未派出訂單，分析可能原因並給具體改善建議
3. 若一切正常，給出簡短的正面確認

排班數據：
- 出車車輛：{vehicles_used} 台
- 已派訂單：{assigned} / {total} 張
- 未派訂單 ID：{unassigned if unassigned else '無'}
- 跳過（無座標）訂單 ID：{skipped if skipped else '無'}
- 總行駛時間：{total_sec // 60} 分鐘
- 各車概況（前 {len(vehicle_summaries)} 台）：
{chr(10).join(vehicle_summaries) if vehicle_summaries else '  （無路線）'}
"""
    return _call_claude(prompt, system=_SYSTEM_DISPATCH)


def evaluate_insertion(
    new_order: dict,
    existing_routes: dict[str, list[dict]],
) -> str:
    """評估將一張新訂單插入現有路線時，哪台車影響最小。"""
    routes_summary = []
    for vid, stops in list(existing_routes.items())[:8]:
        routes_summary.append(
            f"  車輛 {vid}：已有 {len(stops)} 站，"
            f"最後一站 ETA {stops[-1]['eta'] if stops else 'N/A'}"
        )

    prompt = f"""現有排班中，請評估插入以下新訂單哪台車最合適：

新訂單資訊：
- 上車地址：{new_order.get('pickup_address', '未知')}
- 下車地址：{new_order.get('dropoff_address', '未知')}
- 上車時間：{new_order.get('pickup_time', '未知')}
- 車種需求：{new_order.get('vehicle_type', 'normal')}
- 人數：{new_order.get('pax', 1)}
- 需輪椅：{'是' if new_order.get('need_wheelchair') else '否'}

現有各車概況：
{chr(10).join(routes_summary) if routes_summary else '  目前無排班'}

請：
1. 推薦最適合插入的車輛（說明理由）
2. 預估對整體行程的影響
3. 若無法插入，說明原因與替代方案
"""
    return _call_claude(prompt, system=_SYSTEM_DISPATCH)
