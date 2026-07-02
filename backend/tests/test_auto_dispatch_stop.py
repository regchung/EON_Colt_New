"""auto_dispatch_stop 落地測試:模型寫入 + 查詢排序/在車人數欄位。

自動派遣停靠明細的『產生』(compare_day return_stops)依賴 OSRM 矩陣 + dispatch_history,
於真實資料已驗證(07-01/02 各 228×2 / 221×2 停靠)。此處驗模型與讀取契約(免 OSRM)。
"""
from datetime import date, datetime, timezone, timedelta

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.auto_dispatch_stop import AutoDispatchStop

TW = timezone(timedelta(hours=8))
TEST_DATE = date(2099, 3, 3)


def _cleanup(db):
    db.execute(delete(AutoDispatchStop).where(AutoDispatchStop.service_date == TEST_DATE))
    db.commit()


def test_auto_dispatch_stop_roundtrip():
    db = SessionLocal()
    try:
        _cleanup(db)
        rows = [
            AutoDispatchStop(service_date=TEST_DATE, fleet="台北", vehicle_id=1, plate="TEST-A",
                             seq=1, kind="pickup", order_id=101, lng=121.5, lat=25.0,
                             eta=datetime(2099, 3, 3, 8, 30, tzinfo=TW), occupancy=1, is_support=False),
            AutoDispatchStop(service_date=TEST_DATE, fleet="台北", vehicle_id=1, plate="TEST-A",
                             seq=2, kind="pickup", order_id=102, lng=121.51, lat=25.01,
                             eta=datetime(2099, 3, 3, 8, 45, tzinfo=TW), occupancy=2, is_support=True),
            AutoDispatchStop(service_date=TEST_DATE, fleet="台北", vehicle_id=1, plate="TEST-A",
                             seq=3, kind="delivery", order_id=101, lng=121.52, lat=25.02,
                             eta=datetime(2099, 3, 3, 9, 0, tzinfo=TW), occupancy=1, is_support=False),
        ]
        db.add_all(rows)
        db.commit()

        got = list(db.scalars(
            select(AutoDispatchStop)
            .where(AutoDispatchStop.service_date == TEST_DATE)
            .order_by(AutoDispatchStop.vehicle_id, AutoDispatchStop.seq)).all())
        assert [r.seq for r in got] == [1, 2, 3]
        assert [r.occupancy for r in got] == [1, 2, 1]          # 上、上、下 → 在車人數升降
        assert [r.kind for r in got] == ["pickup", "pickup", "delivery"]
        assert got[1].is_support is True                        # 支援標記
        assert got[0].eta.astimezone(TW).strftime("%H:%M") == "08:30"
    finally:
        _cleanup(db)
        db.close()
