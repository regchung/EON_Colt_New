"""系統參數設定服務:預設值 + DB 覆寫 + 型別轉換 + 派遣參數彙整。

即時派遣(`dispatcher.run_dispatch`)讀取本服務取得營運參數;
回測(comparison / pool_suggest)沿用各自模組常數作為固定方法學,以保結果可重現。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.app_setting import AppSetting

# (key, value, type, group, label, description)
DEFAULTS: list[dict] = [
    {"key": "trip_setup_min", "value": "20", "value_type": "int", "group": "派遣規則",
     "label": "每趟上車前置(分)", "description": "上車前作業時間,計入工時"},
    {"key": "trip_teardown_min", "value": "20", "value_type": "int", "group": "派遣規則",
     "label": "每趟下車後置(分)", "description": "下車後作業時間,計入工時"},
    {"key": "max_work_hours", "value": "8", "value_type": "float", "group": "派遣規則",
     "label": "每日工時上限(時)", "description": "每車每日工時上限"},
    {"key": "service_start_hour", "value": "6", "value_type": "int", "group": "派遣規則",
     "label": "服務時段起(時)", "description": "每日最早可接送時間"},
    {"key": "service_end_hour", "value": "18", "value_type": "int", "group": "派遣規則",
     "label": "服務時段迄(時)", "description": "每日最晚『可上車』時間(上車限 06:00–此時)"},
    {"key": "service_completion_buffer_hours", "value": "2", "value_type": "float", "group": "派遣規則",
     "label": "完成緩衝(時)", "description": "車輛可為完成服務時段內上車的趟次,延後營運的時數(如 18:00 上車可跑到 20:00)"},
    {"key": "driver_margin_min", "value": "30", "value_type": "int", "group": "派遣規則",
     "label": "司機前後出勤緩衝(分)", "description": "司機/車輛可在服務時段前後各提早/延後此分鐘出勤(如服務 06–18,司機可 05:30–18:30 出車去接 06:00 早單)"},
    {"key": "pickup_window_min", "value": "30", "value_type": "int", "group": "派遣規則",
     "label": "上車時間窗(分)", "description": "預約時間的容許彈性"},
    {"key": "max_ride_factor", "value": "1.8", "value_type": "float", "group": "派遣規則",
     "label": "最長乘車時間倍率", "description": "乘客在車上時間上限 = 直達車程 × 此倍率 + 緩衝;防止共乘把人載太久(0 或留空=不限)"},
    {"key": "max_ride_grace_min", "value": "30", "value_type": "int", "group": "派遣規則",
     "label": "最長乘車緩衝(分)", "description": "乘車時間上限的固定加項;短程也允許一次併車繞路"},
    {"key": "service_time_factor", "value": "1.0", "value_type": "float", "group": "派遣規則",
     "label": "作業時間係數(省車鬆緊)", "description": "每趟作業時間 = 歷史校準 × 此係數。>1 較保守(省車率↓、貼近人工);<1 較積極(省車率↑)。與上車時間窗同為調整省車率的主旋鈕,不竄改校準真值"},
    {"key": "fleet_isolation", "value": "false", "value_type": "bool", "group": "派遣規則",
     "label": "車隊隔離派遣", "description": "關=集團統一派遣(跨區共乘,最省車);開=分車行派(台北車專派台北趟、新北專派新北趟)。僅隔離台北/新北;神同行/基隆/校車/日照/不拘不限區,由地理自然歸位、池滿可跨區。開啟換取各車行獨立管理與帳務清晰"},
    {"key": "fleet_isolation_fallback", "value": "true", "value_type": "bool", "group": "派遣規則",
     "label": "隔離未派自動跨區補救", "description": "僅在車隊隔離開啟時作用。開=若因隔離導致有單排不進本區池,當日自動回退為統一派遣重排,保證不因隔離而漏單;關=嚴格隔離(寧可未派也不跨區,交行控處理)"},
    {"key": "pool_require_consent", "value": "true", "value_type": "bool", "group": "共乘",
     "label": "共乘需同意", "description": "未同意者獨佔整車,不與他人併乘"},
    {"key": "pool_max_detour_min", "value": "15", "value_type": "float", "group": "共乘",
     "label": "共乘最大繞路(分)", "description": "推薦共乘時每位乘客可接受的繞路上限"},
    {"key": "recurring_min_days", "value": "3", "value_type": "int", "group": "共乘",
     "label": "常態共乘對最少同行天數", "description": "達此天數才列為常態共乘對"},
    {"key": "order_cutoff", "value": "17:30", "value_type": "str", "group": "營運",
     "label": "當日截單時間", "description": "之後不再接當日新單(行控流程參考)"},
    {"key": "cost_per_vehicle_day", "value": "2500", "value_type": "float", "group": "成本",
     "label": "每車日成本(NT$)", "description": "單車單日總成本(司機薪資+車輛攤提+油料保險),用於把省下車日換算成金額"},
    {"key": "annual_service_days", "value": "300", "value_type": "int", "group": "成本",
     "label": "年營運天數", "description": "每年實際出車天數,用於年化省下成本"},
    {"key": "fixed_route_default_no_pool", "value": "true", "value_type": "bool", "group": "固定行程",
     "label": "固定趟預設不可併", "description": "固定趟(校車/日照等)各釘各車,不與其他趟併乘"},
    {"key": "fixed_route_multistop_buffer_min", "value": "30", "value_type": "int", "group": "固定行程",
     "label": "固定趟多站緩衝(分)", "description": "估算固定趟佔用時間時,於頭尾直達車程外加的多站(中途上下車)緩衝;有實際佔用時間者以實際為準"},
    {"key": "fixed_route_min_occupancy_min", "value": "40", "value_type": "int", "group": "固定行程",
     "label": "固定趟佔用時間下限(分)", "description": "估算固定趟佔用時間的下限,避免短程被低估"},
]
_DEFAULT_MAP = {d["key"]: d for d in DEFAULTS}


def _coerce(value, value_type: str):
    if value is None:
        return None
    if value_type == "int":
        return int(float(value))
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")
    return str(value)


def seed_defaults(db: Session) -> int:
    """補齊缺少的預設參數(冪等)。回傳新增筆數。"""
    existing = {k for (k,) in db.execute(select(AppSetting.key)).all()}
    added = 0
    for d in DEFAULTS:
        if d["key"] not in existing:
            db.add(AppSetting(**d))
            added += 1
    if added:
        db.commit()
    return added


def get(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    if row is not None:
        return _coerce(row.value, row.value_type)
    d = _DEFAULT_MAP.get(key)
    if d is not None:
        return _coerce(d["value"], d["value_type"])
    return default


def list_all(db: Session) -> list[AppSetting]:
    return list(db.scalars(select(AppSetting).order_by(AppSetting.group, AppSetting.key)).all())


def dispatch_params(db: Session) -> dict:
    """即時派遣用的營運參數(已換算成秒/旗標)。"""
    return {
        "setup_sec": get(db, "trip_setup_min", 20) * 60,
        "teardown_sec": get(db, "trip_teardown_min", 20) * 60,
        "day_start_sec": int(get(db, "service_start_hour", 6) * 3600),
        "day_end_sec": int(get(db, "service_end_hour", 18) * 3600),
        "completion_buffer_sec": int(get(db, "service_completion_buffer_hours", 2) * 3600),
        "driver_margin_sec": int(get(db, "driver_margin_min", 30) * 60),
        "max_work_sec": int(get(db, "max_work_hours", 8) * 3600),
        "require_consent": bool(get(db, "pool_require_consent", True)),
        "pickup_window_min": get(db, "pickup_window_min", 30),
        "max_ride_factor": float(get(db, "max_ride_factor", 1.6) or 0),
        "max_ride_grace_sec": int(get(db, "max_ride_grace_min", 25) * 60),
        "service_factor": float(get(db, "service_time_factor", 1.0) or 1.0),
        "fleet_isolation": bool(get(db, "fleet_isolation", False)),
        "fleet_isolation_fallback": bool(get(db, "fleet_isolation_fallback", True)),
    }


def fixed_route_params(db: Session) -> dict:
    """固定行程(既定區塊)全域參數。"""
    return {
        "default_no_pool": bool(get(db, "fixed_route_default_no_pool", True)),
        "multistop_buffer_min": int(get(db, "fixed_route_multistop_buffer_min", 30)),
        "min_occupancy_min": int(get(db, "fixed_route_min_occupancy_min", 40)),
    }
