"""What-if(唯讀):把共乘收到最緊(強制不併車,固定趟除外)對省車/未派/併車率的影響。

在抽樣服務日上,對每個 (車行, 日) 各跑兩次 comparison.compare_day:
  A 現況(force_no_pool=False)   B 強制不併車(force_no_pool=True)
比較:自動用車數、未派數、併車率(由 stops 的乘車區間重疊算)。不寫任何表。

用法(可選抽樣天數):
  docker compose exec -T backend python -m scripts.whatif_no_pool 15
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.order import Order
from app.services import comparison

TW = timezone(timedelta(hours=8))


def _mins(dt):
    if not dt:
        return None
    t = dt.astimezone(TW)
    return t.hour * 60 + t.minute


def pool_rate_from_stops(stops):
    """stops: [{vehicle_id,kind,order_id,eta}...] → 併車率(乘車區間與他趟重疊之趟數/總趟數)。"""
    pk, dp = {}, {}
    for s in stops:
        if not s.get("order_id"):
            continue
        k = (s["vehicle_id"], s["order_id"])
        (pk if s["kind"] == "pickup" else dp)[k] = _mins(s.get("eta"))
    by_veh = defaultdict(list)
    for k, pt in pk.items():
        if pt is None:
            continue
        dt = dp.get(k)
        by_veh[k[0]].append((pt, dt if (dt and dt > pt) else pt + 20))
    pooled = tot = 0
    for veh, iv in by_veh.items():
        n = len(iv)
        tot += n
        flag = [False] * n
        for i in range(n):
            for j in range(i + 1, n):
                if iv[i][0] < iv[j][1] - 1 and iv[j][0] < iv[i][1] - 1:
                    flag[i] = flag[j] = True
        pooled += sum(flag)
    return pooled, tot


def main():
    n_days = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    db = SessionLocal()
    try:
        # 有 done 訂單的 (車行,日);抽樣日期均勻取樣
        pairs = list(db.execute(
            select(Order.service_date, Order.fleet).where(Order.status == "done").distinct()
        ).all())
        dates = sorted({d for d, _ in pairs})
        if len(dates) > n_days:
            step = len(dates) / n_days
            dates = [dates[int(i * step)] for i in range(n_days)]
        dsel = set(dates)
        fleets_by_date = defaultdict(set)
        for d, f in pairs:
            if d in dsel and f:
                fleets_by_date[d].add(f)

        print(f"抽樣 {len(dates)} 日(共同方法學 compare_day,OSRM)  {dates[0]} ~ {dates[-1]}\n")
        agg = {"A": [0, 0, 0, 0], "B": [0, 0, 0, 0]}   # veh, unassigned, pooled, trips
        print(f"  {'日期':<12}{'車行':<8}{'現況車/未派/併%':>20}{'不併車/未派/併%':>22}")
        for d in dates:
            for fl in sorted(fleets_by_date[d]):
                rows = {}
                for tag, fnp in (("A", False), ("B", True)):
                    r = comparison.compare_day(db, fl, d, return_stops=True, force_no_pool=fnp)
                    if not r:
                        rows = None
                        break
                    p, t = pool_rate_from_stops(r.get("stops") or [])
                    rows[tag] = (r["vroom_vehicles"], r["vroom_unassigned"], p, t)
                if not rows:
                    continue
                for tag in ("A", "B"):
                    v, u, p, t = rows[tag]
                    agg[tag][0] += v; agg[tag][1] += u; agg[tag][2] += p; agg[tag][3] += t
                va, ua, pa, ta = rows["A"]
                vb, ub, pb, tb = rows["B"]
                print(f"  {str(d):<12}{fl:<8}"
                      f"{f'{va}/{ua}/{100*pa/ta if ta else 0:.0f}%':>20}"
                      f"{f'{vb}/{ub}/{100*pb/tb if tb else 0:.0f}%':>22}")

        print("\n=== 彙總(抽樣日合計)===")
        for tag, name in (("A", "現況(可併車)"), ("B", "強制不併車")):
            v, u, p, t = agg[tag]
            print(f"  {name:<12} 自動用車 {v}  未派 {u}  併車率 {100*p/t if t else 0:.1f}%")
        dv = agg["B"][0] - agg["A"][0]
        du = agg["B"][1] - agg["A"][1]
        print(f"\n  → 強制不併車 vs 現況: 用車 {dv:+d} 台"
              f"({100*dv/agg['A'][0] if agg['A'][0] else 0:+.1f}%)、未派 {du:+d} 趟;"
              f"併車率 {100*agg['A'][2]/agg['A'][3] if agg['A'][3] else 0:.1f}% → "
              f"{100*agg['B'][2]/agg['B'][3] if agg['B'][3] else 0:.1f}%")
    finally:
        db.close()


if __name__ == "__main__":
    main()
