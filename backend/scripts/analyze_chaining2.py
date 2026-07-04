"""接續規則進階:①分車行對照 ②來回趟(同乘客往返)偵測。純唯讀。

②來回趟以「地理反向」偵測(無乘客姓名):同一服務日,存在另一趟其
上車≈本趟下車、下車≈本趟上車(座標四捨五入到 ~110m),且時間在後 →
視為回程。量往返間隔(在院停留)、是否同車承接。
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.dispatch_history import DispatchHistory as H

TW = timezone(timedelta(hours=8))
MAIN_FLEETS = ["台北", "新北", "神同行"]


def hav_km(a_lng, a_lat, b_lng, b_lat):
    if None in (a_lng, a_lat, b_lng, b_lat):
        return None
    R = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat)
    dl = math.radians(b_lng - a_lng)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(x))


def mins(dt):
    if not dt:
        return None
    t = dt.astimezone(TW)
    return t.hour * 60 + t.minute


def q(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return s[max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))]


def med(vals):
    vals = [v for v in vals if v is not None]
    return q(vals, .5) if vals else None


def main():
    db = SessionLocal()
    try:
        rows = list(db.scalars(
            select(H).where(
                H.pickup_time.is_not(None), H.pickup_lng.is_not(None),
                H.dropoff_lng.is_not(None), H.plate.is_not(None),
            )
        ).all())

        # ===== ① 分車行對照 =====
        print("=== ① 分車行接續對照 ===")
        print(f"{'車行':<8}{'趟數':>8}{'上車間距中位':>12}{'空車距km中位':>13}"
              f"{'同區%':>8}{'共乘%':>8}{'每車日趟':>9}")
        for fl in MAIN_FLEETS + ["_其他"]:
            if fl == "_其他":
                sub = [r for r in rows if r.fleet not in MAIN_FLEETS]
            else:
                sub = [r for r in rows if r.fleet == fl]
            if not sub:
                continue
            groups = defaultdict(list)
            for r in sub:
                groups[(r.plate, r.service_date)].append(r)
            gaps, hops, stown, pool, tpvd = [], [], [], [], []
            for _, trips in groups.items():
                trips.sort(key=lambda t: t.pickup_time)
                tpvd.append(len(trips))
                for i in range(1, len(trips)):
                    a, b = trips[i - 1], trips[i]
                    ga, gb = mins(a.pickup_time), mins(b.pickup_time)
                    if ga is not None and gb is not None:
                        gaps.append(gb - ga)
                        pool.append(1 if gb < ga + (a.est_minutes or 0) - 1 else 0)
                    k = hav_km(a.dropoff_lng, a.dropoff_lat, b.pickup_lng, b.pickup_lat)
                    if k is not None:
                        hops.append(k)
                    if a.dropoff_town and b.pickup_town:
                        stown.append(1 if a.dropoff_town == b.pickup_town else 0)
            name = "其他" if fl == "_其他" else fl
            print(f"{name:<8}{len(sub):>8,}{med(gaps) or 0:>10.0f} 分{med(hops) or 0:>11.1f}km"
                  f"{100*sum(stown)/len(stown) if stown else 0:>7.0f}%"
                  f"{100*sum(pool)/len(pool) if pool else 0:>7.1f}%{med(tpvd) or 0:>7.0f} 趟")

        # ===== ② 來回趟偵測(地理反向)=====
        print("\n=== ② 來回趟(往返)偵測 ===")
        by_date = defaultdict(list)
        for r in rows:
            by_date[r.service_date].append(r)

        def key(lng, lat):
            return (round(lng, 3), round(lat, 3))   # ~110m

        total_trips = 0
        outbound_matched = 0
        dwell_mins = []          # 在院/目的地停留 = 回程上車 − 去程下車(估)
        same_vehicle = []        # 回程是否同一台車
        rt_by_fleet = Counter()
        rt_total_by_fleet = Counter()

        for d, trips in by_date.items():
            # 建索引:pickup_key → 該日各趟
            idx = defaultdict(list)
            for t in trips:
                idx[key(t.pickup_lng, t.pickup_lat)].append(t)
            for a in trips:
                total_trips += 1
                rt_total_by_fleet[a.fleet] += 1
                a_pk = key(a.pickup_lng, a.pickup_lat)
                a_dk = key(a.dropoff_lng, a.dropoff_lat)
                a_t = mins(a.pickup_time)
                if a_t is None:
                    continue
                # 找回程:上車≈A下車、下車≈A上車、時間在 A 之後
                best = None
                for b in idx.get(a_dk, []):
                    if b is a:
                        continue
                    if key(b.dropoff_lng, b.dropoff_lat) != a_pk:
                        continue
                    b_t = mins(b.pickup_time)
                    if b_t is None or b_t <= a_t:
                        continue
                    if best is None or b_t < mins(best.pickup_time):
                        best = b
                if best is not None:
                    outbound_matched += 1
                    rt_by_fleet[a.fleet] += 1
                    dwell = mins(best.pickup_time) - (a_t + (a.est_minutes or 0))
                    dwell_mins.append(dwell)
                    same_vehicle.append(1 if best.plate == a.plate else 0)

        print(f"  總趟數: {total_trips:,}")
        print(f"  可辨識為『去程』(有對應回程)的趟數: {outbound_matched:,} "
              f"({100*outbound_matched/total_trips:.1f}%)")
        print(f"  → 往返配對趟數(去+回)佔比約: {200*outbound_matched/total_trips:.1f}%")
        if dwell_mins:
            print(f"  在目的地停留(回程上車 − 去程估下車): "
                  f"中位={q(dwell_mins,.5):.0f} 分  Q1={q(dwell_mins,.25):.0f}  Q3={q(dwell_mins,.75):.0f}")
        if same_vehicle:
            print(f"  回程由『同一台車』承接比例: {100*sum(same_vehicle)/len(same_vehicle):.1f}%")
        print(f"  分車行往返率(去程可配對/該車行總趟):")
        for fl in MAIN_FLEETS:
            t = rt_total_by_fleet.get(fl, 0)
            if t:
                print(f"    {fl}: {100*rt_by_fleet.get(fl,0)/t:.1f}%  (回程同車比例後續可再切)")

        # 停留時間分桶
        if dwell_mins:
            print(f"\n  在院停留分佈:")
            for lo, hi in [(-9999, 30), (30, 60), (60, 90), (90, 120), (120, 180), (180, 9999)]:
                c = len([x for x in dwell_mins if lo <= x < hi])
                lbl = (f"<30分" if lo < 0 else f"{lo}-{hi}分" if hi < 9999 else f"{lo}分以上")
                print(f"    {lbl:>10}: {100*c/len(dwell_mins):5.1f}%")
    finally:
        db.close()


if __name__ == "__main__":
    main()
