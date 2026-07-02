"""共乘同意規則:預設不同意,唯一例外為共乘欄位值含『同意』(且非『不同意』)。"""
from app.services.schedule_import import _is_consent, _consent_col
from app.services.importer import _pool_consent


def test_is_consent_only_when_contains_agree():
    assert _is_consent("同意") is True
    assert _is_consent(" 同意 ") is True
    assert _is_consent("願意共乘(同意)") is True
    assert _is_consent("不同意") is False        # 含『同意』但為『不同意』
    assert _is_consent("否") is False
    assert _is_consent("") is False
    assert _is_consent(None) is False
    assert _is_consent("是") is False             # 規則只認『同意』二字,不認『是/Y』


def test_importer_pool_consent_same_rule():
    assert _pool_consent("同意") is True
    assert _pool_consent("不同意") is False
    assert _pool_consent(None) is False
    assert _pool_consent("Y") is False


def test_consent_col_prefers_agree_column_over_group():
    cols = ["姓名", "共乘組別", "共乘訂單編號", "共乘同意"]
    assert _consent_col(cols) == "共乘同意"
    # 只有組別/訂單編號 → 不當作「同意欄」(組別走另一條推定規則,見匯入邏輯)
    assert _consent_col(["姓名", "共乘組別", "共乘訂單編號"]) is None
