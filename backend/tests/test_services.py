"""服務層純函式 / 輕量單元測試(多數不需資料庫;settings 部分用共用 DB,皆冪等)。

涵蓋:settings 型別轉換與預設、roster 時間換算、comparison 時區換算(鎖定曾發生的
UTC→+08 上車時間 bug)、zone_affinity 硬條件、forecast weekday 名稱。
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.db.session import SessionLocal
from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import comparison, forecast, roster
from app.services import settings as settings_svc


# ---------- settings._coerce ----------
@pytest.mark.parametrize("value,vtype,expected", [
    ("20", "int", 20),
    ("20.9", "int", 20),
    ("8", "float", 8.0),
    ("2500", "float", 2500.0),
    ("true", "bool", True),
    ("False", "bool", False),
    ("是", "bool", True),
    ("0", "bool", False),
    ("17:30", "str", "17:30"),
    (None, "int", None),
])
def test_settings_coerce(value, vtype, expected):
    assert settings_svc._coerce(value, vtype) == expected


def test_settings_defaults_integrity():
    keys = [d["key"] for d in settings_svc.DEFAULTS]
    assert len(keys) == len(set(keys)), "預設參數 key 必須唯一"
    valid_types = {"int", "float", "bool", "str"}
    for d in settings_svc.DEFAULTS:
        assert d["value_type"] in valid_types
        assert d["group"] and d["label"]
        # 預設值需可被自身型別正確轉換
        settings_svc._coerce(d["value"], d["value_type"])
    # #2 新增的成本參數需在列
    assert "cost_per_vehicle_day" in keys
    assert "annual_service_days" in keys


def test_settings_seed_get_dispatch_params():
    db = SessionLocal()
    try:
        settings_svc.seed_defaults(db)          # 冪等
        assert settings_svc.seed_defaults(db) == 0  # 第二次不再新增
        assert settings_svc.get(db, "cost_per_vehicle_day") == 2500.0
        assert settings_svc.get(db, "不存在的key", "fallback") == "fallback"
        p = settings_svc.dispatch_params(db)
        assert p["setup_sec"] == 20 * 60
        assert p["max_work_sec"] == 8 * 3600
        assert p["day_start_sec"] == 6 * 3600
        assert isinstance(p["require_consent"], bool)
    finally:
        db.close()


# ---------- roster._secs ----------
def test_roster_secs():
    assert roster._secs(time(6, 30)) == 6 * 3600 + 30 * 60
    assert roster._secs(time(0, 0)) == 0
    assert roster._secs(None) is None


# ---------- comparison 時區換算(鎖定 +08 bug) ----------
def test_comparison_secs_tw_converts_utc_to_taipei():
    # 22:30 UTC == 隔日 06:30 台北 → 23400 秒(曾因未轉時區誤判為 22:30 → 大量未派)
    dt = datetime(2025, 1, 1, 22, 30, tzinfo=timezone.utc)
    assert comparison._secs_tw(dt) == 6 * 3600 + 30 * 60
    # 03:00 UTC == 11:00 台北
    dt2 = datetime(2025, 6, 1, 3, 0, tzinfo=timezone.utc)
    assert comparison._secs_tw(dt2) == 11 * 3600


def test_comparison_secs_tw_naive_passthrough():
    # 無時區資訊者直接以牆鐘秒數計
    dt = datetime(2025, 1, 1, 9, 15)
    assert comparison._secs_tw(dt) == 9 * 3600 + 15 * 60


def test_comparison_plain_secs():
    assert comparison._secs(time(18, 0)) == 18 * 3600


# ---------- zone_affinity._vehicle_feasible(純硬條件) ----------
def _veh(**kw):
    base = dict(type="normal", seats=4, active=True)
    base.update(kw)
    return Vehicle(**base)


def _ord(**kw):
    base = dict(vehicle_type="normal", pax=1, need_wheelchair=False)
    base.update(kw)
    return Order(**base)


def test_zone_feasible_welfare_required():
    from app.services.zone_affinity import _vehicle_feasible
    ok, reason = _vehicle_feasible(_veh(type="normal"), _ord(vehicle_type="welfare"))
    assert ok is False and reason == "需福祉車"
    ok2, _ = _vehicle_feasible(_veh(type="welfare"), _ord(vehicle_type="welfare"))
    assert ok2 is True


def test_zone_feasible_seats():
    from app.services.zone_affinity import _vehicle_feasible
    ok, reason = _vehicle_feasible(_veh(seats=2), _ord(pax=3))
    assert ok is False and reason == "座位不足"


def test_zone_feasible_inactive():
    from app.services.zone_affinity import _vehicle_feasible
    ok, reason = _vehicle_feasible(_veh(active=False), _ord())
    assert ok is False and reason == "車輛停用"


def test_zone_feasible_ok():
    from app.services.zone_affinity import _vehicle_feasible
    ok, reason = _vehicle_feasible(_veh(seats=4), _ord(pax=2))
    assert ok is True and reason == ""


# ---------- forecast 常數 ----------
def test_forecast_weekday_names():
    assert len(forecast.WD_NAMES) == 7
    assert forecast.WD_NAMES[0] == "週一"
    assert forecast.WD_NAMES[6] == "週日"


# ---------- doc_ingest(文件智慧匯入,純函式) ----------
def test_doc_ingest_extract_text_csv():
    from app.services import doc_ingest
    txt = doc_ingest.extract_text("x.csv", "服務日期,上車\n2026-06-20,甲\n".encode("utf-8"))
    assert "服務日期" in txt and "2026-06-20" in txt


def test_doc_ingest_unsupported_ext():
    from app.services import doc_ingest
    with pytest.raises(ValueError):
        doc_ingest.extract_text("x.zip", b"...")


def test_doc_ingest_strip_json_fence():
    from app.services import doc_ingest
    assert doc_ingest._strip_json('```json\n[{"a":1}]\n```') == '[{"a":1}]'
    assert doc_ingest._strip_json('前言[{"a":1}]後語') == '[{"a":1}]'


def test_doc_ingest_coerce():
    from app.services import doc_ingest
    o = doc_ingest._coerce({
        "pickup_time": "09:00", "vehicle_type": "福祉車", "pax": "2",
        "allow_pool": "是", "need_wheelchair": "N",
        "service_date": "2026-06-20", "pickup_address": "A", "dropoff_address": "B",
    }, None)
    assert o["vehicle_type"] == "welfare"
    assert o["pax"] == 2
    assert o["allow_pool"] is True
    assert o["need_wheelchair"] is False
    assert o["pickup_time"] == "2026-06-20T09:00:00"


def test_doc_ingest_coerce_default_date():
    from app.services import doc_ingest
    o = doc_ingest._coerce({"pickup_address": "A", "dropoff_address": "B"}, "2026-07-01")
    assert o["service_date"] == "2026-07-01"


# ---------- assistant(調度員 AI 助理) ----------
def test_assistant_tools_schema_integrity():
    from app.services import assistant
    names = [t["name"] for t in assistant.TOOLS]
    assert len(names) == len(set(names)), "工具名稱需唯一"
    # 每個工具都要有對應執行器,反之亦然
    assert set(names) == set(assistant._EXECUTORS)
    for t in assistant.TOOLS:
        assert t["description"] and t["input_schema"]["type"] == "object"


def test_assistant_chat_no_key_graceful():
    from app.core.config import settings as cfg
    from app.services import assistant
    if cfg.ANTHROPIC_API_KEY:
        pytest.skip("已設定 ANTHROPIC_API_KEY,跳過無金鑰降級測試")
    db = SessionLocal()
    try:
        r = assistant.chat(db, [{"role": "user", "content": "今天幾單?"}])
        assert "ANTHROPIC_API_KEY" in r["reply"]
        assert r["tool_trace"] == []
    finally:
        db.close()


def test_assistant_run_tool_unknown():
    from app.services import assistant
    db = SessionLocal()
    try:
        assert "error" in assistant._run_tool(db, "no_such_tool", {})
    finally:
        db.close()


# ---------- 時區收尾:寫入一律存台灣 +08 ----------
def test_order_schema_naive_pickup_gets_tw():
    from app.schemas.order import OrderCreate
    oc = OrderCreate(service_date="2026-06-25", pickup_time="2026-06-25T09:00:00",
                     pickup_address="A", dropoff_address="B")
    assert oc.pickup_time.utcoffset() == timedelta(hours=8)
    assert oc.pickup_time.hour == 9   # 不被位移


def test_order_schema_aware_pickup_preserved():
    from app.schemas.order import OrderCreate
    oc = OrderCreate(service_date="2026-06-25", pickup_time="2026-06-25T09:00:00+08:00",
                     pickup_address="A", dropoff_address="B")
    assert oc.pickup_time.utcoffset() == timedelta(hours=8)
    assert oc.pickup_time.hour == 9


def test_importer_parse_time_is_tw():
    from app.services.importer import _parse_time_to_dt
    dt = _parse_time_to_dt("15:00", date(2026, 6, 25))
    assert dt.utcoffset() == timedelta(hours=8)
    assert dt.hour == 15   # 與 comparison._secs_tw 一致:astimezone(TW) 仍是 15:00


def test_importer_tw_roundtrip_with_secs_tw():
    """匯入的上車時間經 comparison._secs_tw 換算,應回到原本的台灣牆鐘秒數(不位移)。"""
    from app.services.importer import _parse_time_to_dt
    dt = _parse_time_to_dt("15:30", date(2026, 6, 25))
    assert comparison._secs_tw(dt) == 15 * 3600 + 30 * 60
