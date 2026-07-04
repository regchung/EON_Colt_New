"""從歷史人工派遣(dispatch_history)反推「調度員接續下一位乘客」的實證規則。

方法:同一 (車牌, 服務日) 依 pickup_time 排序,取連續兩趟 A→B,統計:
  - 上車間距(分)= B上車 - A上車
  - 銜接空車距離(km)= A下車點 → B上車點(haversine)
  - 是否同一行政區(A下車 town == B上車 town)
  - 是否共乘/重疊(B上車 < A下車估;A下車估 = A上車 + est_minutes)
  - 每車每日趟數、福祉一致性、主導行政區集中度
輸出各項的中位數/四分位/比例。純唯讀,不寫任何表。
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.dispatch_history import DispatchHistory as H

TW = timezone(timedelta(hours=8))


def hav_km(a_lng, a_lat, b_lng, b_lat):
    if None in (a_lng, a_lat, b_lng, b_lat):
        return None
    R = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat)
    dl = math.radians(b_lng - a_lng)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(x))


def mins_of_day(dt):
    if not dt:
        return None
    t = dt.astimezone(TW)
    return t.hour * 60 + t.minute


def q(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))
    return s[i]


def stat_line(name, vals, unit=""):
    vals = [v for v in vals if v is not None]
    if not vals:
        print(f"  {name}: (無資料)")
        return
    print(f"  {name}: n={len(vals):,}  中位={q(vals,.5):.1f}{unit}  "
          f"Q1={q(vals,.25):.1f}  Q3={q(vals,.75):.1f}  "
          f"P10={q(vals,.1):.1f}  P90={q(vals,.9):.1f}  平均={sum(vals)/len(vals):.1f}")


def main():
    db = SessionLocal()
    try:
        # 只取真正成行(SERVED-like)且有座標、有上車時間的紀錄
        rows = list(db.scalars(
            select(H).where(
                H.pickup_time.is_not(None),
                H.pickup_lng.is_not(None),
                H.dropoff_lng.is_not(None),
                H.plate.is_not(None),
            )
        ).all())
        print(f"=== 資料概況 ===")
        print(f"  總紀錄(有座標+時間+車牌): {len(rows):,}")
        dates = {r.service_date for r in rows}
        fleets = Counter(r.fleet for r in rows)
        print(f"  服務日數: {len(dates)}  範圍: {min(dates)} ~ {max(dates)}")
        print(f"  車行分佈: " + ", ".join(f"{k}={v:,}" for k, v in fleets.most_common()))

        # 依 (車牌, 日) 分組
        groups = defaultdict(list)
        for r in rows:
            groups[(r.plate, r.service_date)].append(r)

        gaps_pickup, hop_km, same_town = [], [], []
        overlap_flags = []          # 是否與前趟共乘(時間重疊)
        trips_per_vd = []           # 每車每日趟數
        dom_share = []              # 每車每日主導行政區佔比
        welfare_consistent = []     # 福祉車一天是否只做福祉
        gap_when_chain, gap_when_pool = [], []

        for (plate, d), trips in groups.items():
            trips = [t for t in trips if t.pickup_time]
            trips.sort(key=lambda t: t.pickup_time)
            trips_per_vd.append(len(trips))

            # 主導行政區集中度(用上車 town)
            towns = Counter(t.pickup_town for t in trips if t.pickup_town)
            if towns:
                dom_share.append(towns.most_common(1)[0][1] / len(trips))

            # 福祉一致性
            wtypes = [bool(t.vehicle_type_req and "福祉" in t.vehicle_type_req) for t in trips]
            if any(wtypes):
                welfare_consistent.append(1 if all(wtypes) else 0)

            for i in range(1, len(trips)):
                a, b = trips[i - 1], trips[i]
                ga = mins_of_day(a.pickup_time)
                gb = mins_of_day(b.pickup_time)
                if ga is not None and gb is not None:
                    gap = gb - ga
                    gaps_pickup.append(gap)
                    # A 下車估 = A上車 + est
                    a_drop_est = ga + (a.est_minutes or 0)
                    is_pool = gb < a_drop_est - 1   # B上車早於A估計下車 → 車上重疊(共乘)
                    overlap_flags.append(1 if is_pool else 0)
                    (gap_when_pool if is_pool else gap_when_chain).append(gap)
                k = hav_km(a.dropoff_lng, a.dropoff_lat, b.pickup_lng, b.pickup_lat)
                if k is not None:
                    hop_km.append(k)
                if a.dropoff_town and b.pickup_town:
                    same_town.append(1 if a.dropoff_town == b.pickup_town else 0)

        print(f"\n=== 連續兩趟 A→B 的接續規則(n={len(gaps_pickup):,} 對)===")
        stat_line("上車間距(B上車 − A上車)", gaps_pickup, " 分")
        stat_line("銜接空車距離(A下車→B上車)", hop_km, " km")
        print(f"  A下車與B上車『同一行政區』比例: {100*sum(same_town)/len(same_town):.1f}%  (n={len(same_town):,})")
        print(f"  與前趟『時間重疊/共乘』比例: {100*sum(overlap_flags)/len(overlap_flags):.1f}%  (n={len(overlap_flags):,})")
        stat_line("  ↳ 純接續(不重疊)之上車間距", gap_when_chain, " 分")
        stat_line("  ↳ 共乘(重疊)之上車間距", gap_when_pool, " 分")

        print(f"\n=== 每車每日型態 ===")
        stat_line("每車每日趟數", trips_per_vd, " 趟")
        stat_line("主導行政區佔該車當日趟數比", [x * 100 for x in dom_share], "%")
        if welfare_consistent:
            print(f"  福祉車當日『只做福祉單』比例: {100*sum(welfare_consistent)/len(welfare_consistent):.1f}%  "
                  f"(有福祉單的車日 n={len(welfare_consistent):,})")

        # 間距分佈分桶
        print(f"\n=== 上車間距分佈(判斷『多久接下一位』)===")
        buckets = [(0, 15), (15, 30), (30, 45), (45, 60), (60, 90), (90, 120), (120, 9999)]
        tot = len([g for g in gaps_pickup if g >= 0])
        for lo, hi in buckets:
            c = len([g for g in gaps_pickup if lo <= g < hi])
            lbl = f"{lo}-{hi}分" if hi < 9999 else f"{lo}分以上"
            bar = "█" * int(40 * c / tot) if tot else ""
            print(f"  {lbl:>10}: {100*c/tot:5.1f}%  {bar}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
