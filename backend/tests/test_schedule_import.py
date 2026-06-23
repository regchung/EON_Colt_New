"""schedule_import 純函式測試:民國日期解析、欄名容錯、假單略過邏輯。

求解/地理編碼相關屬整合層(需 Map8/OSRM),此處只鎖純函式,CI 可離線跑。
"""
from datetime import date

from app.services import schedule_import as si


def test_roc_date_parse():
    assert si._roc_date("1150623") == date(2026, 6, 23)
    assert si._roc_date("1000101") == date(2011, 1, 1)
    assert si._roc_date(None) is None
    assert si._roc_date("abc") is None
    assert si._roc_date("115063") is None        # 不足 7 碼
    assert si._roc_date("1151323") is None        # 月份非法


def test_find_col_tolerates_newline_and_spaces():
    cols = ["車型需求", "起始時段-小時\n (24小時制)", "起始時段-分鐘", "駕駛姓名", "姓名"]
    assert si._find_col(cols, "起始時段", "小時") == "起始時段-小時\n (24小時制)"
    assert si._find_col(cols, "起始時段", "分鐘") == "起始時段-分鐘"
    assert si._find_col(cols, "車型需求") == "車型需求"
    assert si._find_col(cols, "不存在") is None


def test_fake_order_type_constant():
    # 假單(測試/占位,如『小驢駒先生A』)應被歸入略過集合
    assert "假單" in si.SKIP_ORDER_TYPES
    assert "正常" not in si.SKIP_ORDER_TYPES
    assert "候補" not in si.SKIP_ORDER_TYPES


def test_numeric_helpers():
    assert si._i("5") == 5
    assert si._i(None) is None
    assert si._f("24.3") == 24.3
    assert si._s("  ") is None
    assert si._s(" RCE-2700 ") == "RCE-2700"
