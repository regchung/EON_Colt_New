"""定位併車來源(唯讀):用同一 occupancy>=2 指標比人工 vs 自動,並拆自動併車是否來自固定趟。

occupancy 指標:依上車(+pax)/下車(-pax)追蹤在車人數,計「上車當下在車>=2」之比例。
人工:用 dispatch_history 的 pickup_time + est_minutes 還原上下車事件。
自動:用 comparison.compare_day(live) 的 stops occupancy;並用 fixed_route_match 標記固定趟。
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.dispatch_history import DispatchHistory as H
from app.models.order import Order
from app.services import comparison, fixed_route_match

TW = timezone(timedelta(hours=8))


def mn(dt):
    if not dt:
        return None
    t = dt.astimezone(TW)
    return t.hour * 60 + t.minute


def human_occ2(rows):
    """rows: dispatch_history of one (plate,date). 回傳 (跨單併車上車數, 上車總數)。
    併車 = 上車當下『另有其他訂單』仍在車上(以訂單數計,非人數;排除單一訂單多人)。"""
    ev = []   # (time, kind, oid)
    for i, r in enumerate(rows):
        pt = mn(r.pickup_time)
        if pt is None:
            continue
        dur = r.est_minutes or 20
        ev.append((pt, "P", i))
        ev.append((pt + dur, "D", i))
    ev.sort(key=lambda e: (e[0], e[1] == "P"))   # 同刻先下車再上車
    onboard = set()
    ge2 = tot = 0
    for t, k, oid in ev:
        if k == "P":
            tot += 1
            if len(onboard) >= 1:   # 已有他單在車 → 跨單併車
                ge2 += 1
            onboard.add(oid)
        else:
            onboard.discard(oid)
    return ge2, tot


def main():
    n_days = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    db = SessionLocal()
    try:
        pairs = list(db.execute(
            select(Order.service_date, Order.fleet).where(Order.status == "done").distinct()).all())
        dates = sorted({d for d, _ in pairs})
        if len(dates) > n_days:
            step = len(dates) / n_days
            dates = [dates[int(i * step)] for i in range(n_days)]
        dsel = set(dates)
        fleets_by_date = defaultdict(set)
        for d, f in pairs:
            if d in dsel and f:
                fleets_by_date[d].add(f)

        H_ge2 = H_tot = 0
        A_ge2 = A_tot = 0
        A_fixed_pick = A_fixed_ge2 = 0     # 固定趟的上車 / 其中 occ>=2
        A_nonfixed_ge2 = A_nonfixed_pick = 0

        print(f"抽樣 {len(dates)} 日\n")
        print(f"  {'日期':<12}{'車行':<8}{'人工併%':>9}{'自動併%':>9}{'固定趟占自動上車%':>18}")
        for d in dates:
            fr = fixed_route_match.match_for_date(db, d)
            pins = set(fr["pins"].keys())
            for fl in sorted(fleets_by_date[d]):
                # 人工
                hrows = list(db.scalars(select(H).where(
                    H.fleet == fl, H.service_date == d, H.status == comparison.SERVED,
                    H.pickup_time.is_not(None)).all() if False else select(H).where(
                    H.fleet == fl, H.service_date == d, H.status == comparison.SERVED,
                    H.pickup_time.is_not(None))).all())
                hvd = defaultdict(list)
                for r in hrows:
                    hvd[r.plate].append(r)
                hg = ht = 0
                for plate, rs in hvd.items():
                    g, t = human_occ2(rs)
                    hg += g; ht += t
                # 自動(live)
                r = comparison.compare_day(db, fl, d, return_stops=True)
                if not r:
                    continue
                stops = r.get("stops") or []
                # 既定區塊/固定趟:occupancy_min 或 name-pin
                occ_orders = {o.id for o in db.scalars(select(Order).where(
                    Order.fleet == fl, Order.service_date == d,
                    Order.occupancy_min.is_not(None))).all()}
                fixed_ids = pins | occ_orders
                # 跨單併車:同車 seq 序追蹤『在車訂單集合』,上車時若已有他單 → 併車
                by_v = defaultdict(list)
                for s in stops:
                    by_v[s["vehicle_id"]].append(s)
                ag = at = 0
                for vid, sl in by_v.items():
                    onb = set()
                    for s in sorted(sl, key=lambda x: x["seq"]):
                        oid = s.get("order_id")
                        if s["kind"] == "pickup":
                            at += 1
                            pooled = len(onb) >= 1
                            if pooled:
                                ag += 1
                            if oid in fixed_ids:
                                A_fixed_pick += 1
                                if pooled:
                                    A_fixed_ge2 += 1
                            else:
                                A_nonfixed_pick += 1
                                if pooled:
                                    A_nonfixed_ge2 += 1
                            onb.add(oid)
                        else:
                            onb.discard(oid)
                H_ge2 += hg; H_tot += ht
                A_ge2 += ag; A_tot += at
                fixp = sum(1 for s in stops if s["kind"] == "pickup" and s.get("order_id") in fixed_ids)
                print(f"  {str(d):<12}{fl:<8}"
                      f"{100*hg/ht if ht else 0:>8.0f}%{100*ag/at if at else 0:>8.0f}%"
                      f"{100*fixp/at if at else 0:>16.0f}%")

        print("\n=== 彙總(同一 occupancy>=2 指標)===")
        print(f"  人工 併車率: {100*H_ge2/H_tot if H_tot else 0:.1f}%  ({H_ge2}/{H_tot})")
        print(f"  自動 併車率: {100*A_ge2/A_tot if A_tot else 0:.1f}%  ({A_ge2}/{A_tot})")
        print(f"\n  自動併車拆解:")
        print(f"    固定趟上車 {A_fixed_pick}  其中併車 {A_fixed_ge2} "
              f"({100*A_fixed_ge2/A_fixed_pick if A_fixed_pick else 0:.0f}%)")
        print(f"    非固定上車 {A_nonfixed_pick}  其中併車 {A_nonfixed_ge2} "
              f"({100*A_nonfixed_ge2/A_nonfixed_pick if A_nonfixed_pick else 0:.0f}%)")
        if A_ge2:
            print(f"    → 自動併車中,固定趟貢獻 {100*A_fixed_ge2/A_ge2:.0f}%、非固定 {100*A_nonfixed_ge2/A_ge2:.0f}%")
    finally:
        db.close()


if __name__ == "__main__":
    main()
