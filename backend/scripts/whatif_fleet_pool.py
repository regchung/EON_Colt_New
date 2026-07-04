"""What-if(唯讀):對指定車行『開放共乘』對未派/用車的影響。預設神同行(遠郊)。

對該車行每個有 done 訂單的日子,各跑兩次 comparison.compare_day:
  A 現況(force_pool=False)  B 開放共乘(force_pool=True)
比較:自動用車數、未派數、跨單併車率。不寫任何表。

用法:
  docker compose exec -T backend python -m scripts.whatif_fleet_pool 神同行 30
"""
from __future__ import annotations

import sys
from collections import defaultdict

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.order import Order
from app.services import comparison


def cross_pool(stops):
    """回傳 (跨單併車上車數, 上車總數):同車 seq 序追蹤在車訂單集合。"""
    by_v = defaultdict(list)
    for s in stops:
        by_v[s["vehicle_id"]].append(s)
    ge = tot = 0
    for vid, sl in by_v.items():
        onb = set()
        for s in sorted(sl, key=lambda x: x["seq"]):
            oid = s.get("order_id")
            if s["kind"] == "pickup":
                tot += 1
                if len(onb) >= 1:
                    ge += 1
                onb.add(oid)
            else:
                onb.discard(oid)
    return ge, tot


def main():
    fleet = sys.argv[1] if len(sys.argv) > 1 else "神同行"
    n_days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    db = SessionLocal()
    try:
        dates = sorted({d for (d,) in db.execute(
            select(Order.service_date).where(
                Order.fleet == fleet, Order.status == "done").distinct()).all()})
        if len(dates) > n_days:
            step = len(dates) / n_days
            dates = [dates[int(i * step)] for i in range(n_days)]
        print(f"車行 {fleet}:抽樣 {len(dates)} 日  {dates[0]} ~ {dates[-1]}\n")

        agg = {"A": [0, 0, 0, 0], "B": [0, 0, 0, 0]}   # veh, unassigned, pooled, trips
        print(f"  {'日期':<12}{'訂單':>5}{'現況 車/未派/併%':>18}{'開放共乘 車/未派/併%':>22}")
        for d in dates:
            n_ord = db.scalar(select(__import__('sqlalchemy').func.count()).where(
                Order.fleet == fleet, Order.service_date == d, Order.status == "done"))
            rows = {}
            for tag, fp in (("A", False), ("B", True)):
                r = comparison.compare_day(db, fleet, d, return_stops=True, force_pool=fp)
                if not r:
                    rows = None
                    break
                p, t = cross_pool(r.get("stops") or [])
                rows[tag] = (r["vroom_vehicles"], r["vroom_unassigned"], p, t)
            if not rows:
                continue
            for tag in ("A", "B"):
                for i in range(4):
                    agg[tag][i] += rows[tag][i]
            va, ua, pa, ta = rows["A"]
            vb, ub, pb, tb = rows["B"]
            print(f"  {str(d):<12}{n_ord:>5}"
                  f"{f'{va}/{ua}/{100*pa/ta if ta else 0:.0f}%':>18}"
                  f"{f'{vb}/{ub}/{100*pb/tb if tb else 0:.0f}%':>22}")

        print("\n=== 彙總(抽樣日合計)===")
        for tag, name in (("A", "現況(未同意獨佔)"), ("B", "開放共乘")):
            v, u, p, t = agg[tag]
            print(f"  {name:<16} 用車 {v}  未派 {u}  跨單併車率 {100*p/t if t else 0:.1f}%")
        dv = agg["B"][0] - agg["A"][0]
        du = agg["B"][1] - agg["A"][1]
        print(f"\n  → 開放共乘 vs 現況: 用車 {dv:+d} 台、未派 {du:+d} 趟"
              f"  (未派 {agg['A'][1]} → {agg['B'][1]})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
