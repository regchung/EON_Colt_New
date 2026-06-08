"""匯入解析器單元測試(純函式,不需資料庫)。"""
from app.services.importer import parse_orders


def test_parse_csv_basic():
    csv = (
        "服務日期,上車時間,上車地址,下車地址,車種,輪椅,人數\n"
        "2026-06-10,09:00,台北市A,新北市B,福祉車,Y,2\n"
    ).encode("utf-8")
    payloads, errors = parse_orders("x.csv", csv)
    assert errors == []
    assert len(payloads) == 1
    p = payloads[0]
    assert p["vehicle_type"] == "welfare"
    assert p["need_wheelchair"] is True
    assert p["pax"] == 2
    assert p["pickup_address"] == "台北市A"


def test_parse_normal_car_and_pool_default():
    csv = (
        "服務日期,上車時間,上車地址,下車地址,車種,共乘\n"
        "2026-06-10,10:30,甲,乙,一般車,N\n"
    ).encode("utf-8")
    payloads, errors = parse_orders("x.csv", csv)
    assert not errors and len(payloads) == 1
    assert payloads[0]["vehicle_type"] == "normal"
    assert payloads[0]["allow_pool"] is False


def test_parse_missing_required_columns():
    csv = "foo,bar\n1,2\n".encode("utf-8")
    payloads, errors = parse_orders("x.csv", csv)
    assert payloads == []
    assert errors and "缺少必要欄位" in errors[0]["error"]


def test_unsupported_extension():
    import pytest
    with pytest.raises(ValueError):
        parse_orders("x.txt", b"whatever")
