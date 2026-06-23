"""未派回饋學習建議:把未派紀錄 + 行控回饋 → 可落地的改善建議(縮小人工vs自動缺口)。

流程:
1. 聚合 unassigned_record:依系統原因(reason_code)、行控回饋類別、車行統計。
2. 規則對應 → 參數調整建議(放寬服務時段/上車窗、推共乘、增福祉車、修地址)。
3. (有金鑰時)Claude 產白話診斷;無金鑰時仍回規則式建議。
"""
from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.unassigned_record import UnassignedRecord
from app.services import ai_dispatch

_REASON_LABEL = {
    "out_of_hours": "服務時段外(06:00–18:00 之外)",
    "no_welfare": "無福祉車可用",
    "unroutable": "地址/座標無法路由",
    "suspect_geocode": "座標離營運區過遠(疑地理編碼錯誤)",
    "fleet_saturated": "全車隊滿載(需增車)",
    "solver_margin": "求解邊際(仍有餘力,可重排)",
    "infeasible": "車隊已滿載 / 時間窗無法排入",   # 舊碼,相容歷史紀錄
}


def aggregate(db: Session, fleet: str | None = None) -> dict:
    q = select(UnassignedRecord)
    if fleet:
        q = q.where(UnassignedRecord.fleet == fleet)
    rows = list(db.scalars(q).all())
    by_reason = Counter(r.reason_code for r in rows)
    by_feedback = Counter(r.feedback_category for r in rows if r.feedback_category)
    by_fleet = Counter(r.fleet for r in rows)
    return {
        "total": len(rows),
        "feedback_filled": sum(by_feedback.values()),
        "by_reason": {k: by_reason.get(k, 0) for k in _REASON_LABEL},
        "by_reason_label": {_REASON_LABEL[k]: by_reason.get(k, 0) for k in _REASON_LABEL},
        "by_feedback": dict(by_feedback),
        "by_fleet": dict(by_fleet),
    }


def recommendations(agg: dict) -> list[dict]:
    """規則式建議:action / rationale / impact(可改善的未派趟次估計)。"""
    r = agg["by_reason"]
    fb = agg.get("by_feedback", {})
    recs = []
    if r.get("out_of_hours"):
        recs.append({
            "action": "放寬服務時段或設晚班/早班車",
            "rationale": f"{r['out_of_hours']} 趟落在 06:00–18:00 之外;延後收班(如 18:30)或安排早晚班車可吸收。",
            "impact": r["out_of_hours"], "param": "service_start_hour / service_end_hour",
        })
    if r.get("infeasible"):
        recs.append({
            "action": "放寬上車時間窗 / 增加尖峰車輛",
            "rationale": f"{r['infeasible']} 趟因時間窗或車隊滿載排不進;放寬上車窗(見時間窗敏感度)或加尖峰車。",
            "impact": r["infeasible"], "param": "pickup_window_min",
        })
    if r.get("no_welfare"):
        recs.append({
            "action": "增加福祉車",
            "rationale": f"{r['no_welfare']} 趟需福祉車但無車可派;評估增購/調度福祉車。",
            "impact": r["no_welfare"], "param": "fleet",
        })
    if r.get("unroutable"):
        recs.append({
            "action": "修正地址/座標",
            "rationale": f"{r['unroutable']} 趟上/下車點無法路由;檢查地址簿座標或重新地理編碼。",
            "impact": r["unroutable"], "param": "address_book",
        })
    if r.get("suspect_geocode"):
        recs.append({
            "action": "校正疑似錯誤的地址座標",
            "rationale": f"{r['suspect_geocode']} 趟上/下車座標離營運區過遠(疑地理編碼編到他縣市);"
                         "校正地址簿座標即可恢復可派,非車隊問題。",
            "impact": r["suspect_geocode"], "param": "address_book",
        })
    if r.get("fleet_saturated"):
        recs.append({
            "action": "增派尖峰車輛",
            "rationale": f"{r['fleet_saturated']} 趟在全車隊滿載下排不進;該時段增派車輛可吸收。",
            "impact": r["fleet_saturated"], "param": "fleet",
        })
    if r.get("solver_margin"):
        recs.append({
            "action": "重排或放寬上車窗(車隊仍有餘力)",
            "rationale": f"{r['solver_margin']} 趟車隊仍有閒置/餘力、屬求解邊際;重排或放寬上車窗多可排入。",
            "impact": r["solver_margin"], "param": "pickup_window_min",
        })
    # 行控回饋驅動(若已蒐集)
    fb_map = {
        "司機可加班補位": ("放寬工時上限 / 服務時段", "max_work_hours / service_end_hour"),
        "客戶可調整時間": ("放寬上車時間窗", "pickup_window_min"),
        "實際可共乘": ("推動共乘同意蒐集", "pool_require_consent"),
        "地址或座標有誤": ("修正地址簿座標", "address_book"),
    }
    for cat, n in fb.items():
        if cat in fb_map and n:
            act, param = fb_map[cat]
            recs.append({"action": act,
                         "rationale": f"行控回饋 {n} 筆標記「{cat}」,支持此調整。",
                         "impact": n, "param": param, "from_feedback": True})
    recs.sort(key=lambda x: x["impact"], reverse=True)
    return recs


def insights(db: Session, fleet: str | None = None, use_ai: bool = True) -> dict:
    agg = aggregate(db, fleet)
    recs = recommendations(agg)
    ai_summary = None
    if use_ai and agg["total"]:
        lines = [f"未派總數 {agg['total']}(行控已回饋 {agg['feedback_filled']})。",
                 "系統原因分布:" + "、".join(f"{k} {v}" for k, v in agg["by_reason_label"].items() if v),
                 "規則建議:" + "; ".join(f"{r['action']}(影響約 {r['impact']} 趟)" for r in recs)]
        prompt = (
            "你是長照車隊調度顧問。以下是自動派遣『未排入』訂單的統計與初步建議,"
            "請用繁體中文、條列、具體可行地,給管理者 3–5 點改善行動(縮小人工與自動派遣的覆蓋差距),"
            "並點出最該優先處理的一項。資料:\n" + "\n".join(lines)
        )
        ai_summary = ai_dispatch._call_claude(prompt, max_tokens=800, timeout=45)
    return {"fleet": fleet, "stats": agg, "recommendations": recs, "ai_summary": ai_summary}
