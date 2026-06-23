"""calibration 純函式測試:距離、中位、夾擠、查詢退回邏輯。

analyze()/apply() 需歷史資料(整合層),此處鎖純函式,CI 可離線跑。
"""
from app.services import calibration as CAL


def test_km_haversine():
    # 台北↔台中 ~130–160 km
    assert 120 < CAL._km(121.51, 25.05, 120.68, 24.14) < 180
    assert CAL._km(121.5, 25.0, 121.5, 25.0) == 0


def test_median():
    assert CAL._median([10]) == 10
    assert CAL._median([10, 20, 30]) == 20
    assert CAL._median([10, 20, 30, 40]) == 25
    assert CAL._median([]) == 0.0


def test_clamp_service_min():
    # 下限 12 分、上限 45 分,輸出秒
    assert CAL._clamp_service_min(5) == 12 * 60
    assert CAL._clamp_service_min(20) == 20 * 60
    assert CAL._clamp_service_min(99) == 45 * 60


def test_effective_service_sec_fallback():
    svc = {
        "*": (1200, 1320, 1.0),       # 全域 20/22 分
        "台北": (1200, 1320, 1.0),
        "新北": (1140, 1188, 0.97),
    }
    # 有校準的車行 → 用該車行;福祉取第二值
    assert CAL.effective_service_sec(svc, "新北", False, 9999) == 1140
    assert CAL.effective_service_sec(svc, "新北", True, 9999) == 1188
    # 無校準車行 → 退全域 '*'
    assert CAL.effective_service_sec(svc, "神同行", False, 9999) == 1200
    assert CAL.effective_service_sec(svc, "神同行", True, 9999) == 1320
    # 完全無校準資料 → 退 default
    assert CAL.effective_service_sec({}, "台北", False, 2400) == 2400
