"""人工 vs 系統自動:在同一批服務日、用相同指標比對接續邏輯差異。純唯讀。

人工來源:dispatch_history(SERVED)  自動來源:auto_dispatch_stop(已落地)
限制在兩者共同的服務日,避免日期不對稱。指標一致定義:
  - 每日用車數、每車每日趟數
  - 連續上車間距(分)、連續上車點直線距離(km)
  - 併車率 = 該車日中,乘車時段與他趟重疊之趟數比(人工用 pickup+est 估區間)
  - 往返:去程可配對回程者中,回程同一台車比例
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.dispatch_history import DispatchHistory as H
from app.models.auto_dispatch_stop import AutoDispatchStop as A

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


def mins(dt):
    if not dt:
        return None
    t = dt.astimezone(TW)
    return t.hour * 60 + t.minute


def med(vals):
    vals = sorted(v for v in vals if v is not None)
    return vals[len(vals) // 2] if vals else None


def overlap_count(intervals):
    """intervals: list of (start,end);回傳與至少一個其他區間重疊的個數。"""
    n = len(intervals)
    flag = [False] * n
    for i in range(n):
        si, ei = intervals[i]
        for j in range(i + 1, n):
            sj, ej = intervals[j]
            if si < ej - 1 and sj < ei - 1:   # 重疊(留 1 分容差)
                flag[i] = flag[j] = True
    return sum(flag)


def analyze(vd_trips):
    """vd_trips: {(veh,date): [dict(t=上車分, dur=乘車分, lng,lat,dlng,dlat)]}"""
    used_per_day = defaultdict(set)
    tpvd, gaps, hops, pool_rate = [], [], [], []
    for (veh, d), trips in vd_trips.items():
        trips = [t for t in trips if t["t"] is not None]
        if not trips:
            continue
        used_per_day[d].add(veh)
        trips.sort(key=lambda t: t["t"])
        tpvd.append(len(trips))
        for i in range(1, len(trips)):
            gaps.append(trips[i]["t"] - trips[i - 1]["t"])
            k = hav_km(trips[i - 1]["lng"], trips[i - 1]["lat"],
                       trips[i]["lng"], trips[i]["lat"])
            if k is not None:
                hops.append(k)
        iv = [(t["t"], t["t"] + (t["dur"] or 0)) for t in trips]
        oc = overlap_count(iv)
        pool_rate.append((oc, len(trips)))
    veh_day = [len(s) for s in used_per_day.values()]
    pooled = sum(o for o, _ in pool_rate)
    tot = sum(n for _, n in pool_rate)
    return {
        "veh_per_day_med": med(veh_day),
        "veh_days": sum(veh_day),
        "tpvd_med": med(tpvd),
        "gap_med": med(gaps),
        "hop_med": med(hops),
        "pool_pct": 100 * pooled / tot if tot else 0,
    }


def roundtrip_same_vehicle(rows_by_date, coord, veh, ptime, dtime, est_dur):
    """回傳 (可配對去程數, 回程同車數)。geo 反向,座標 round 3(~110m)。"""
    def key(lng, lat):
        return (round(lng, 3), round(lat, 3))

    def ok(pt):
        return pt and pt[0] is not None and pt[1] is not None
    match, same = 0, 0
    for d, rows in rows_by_date.items():
        idx = defaultdict(list)
        for r in rows:
            pk = coord(r, "p")
            if ok(pk):
                idx[key(*pk)].append(r)
        for a in rows:
            pk, dk = coord(a, "p"), coord(a, "d")
            at = ptime(a)
            if not ok(pk) or not ok(dk) or at is None:
                continue
            best = None
            for b in idx.get(key(*dk), []):
                if b is a:
                    continue
                bdk = coord(b, "d")
                if not ok(bdk) or key(*bdk) != key(*pk):
                    continue
                bt = ptime(b)
                if bt is None or bt <= at:
                    continue
                if best is None or bt < ptime(best):
                    best = b
            if best is not None:
                match += 1
                if veh(best) == veh(a):
                    same += 1
    return match, same


def main():
    db = SessionLocal()
    try:
        # 共同服務日 = auto 有的日期
        auto_dates = set(db.scalars(select(A.service_date).distinct()).all())
        print(f"共同比對服務日數: {len(auto_dates)}  範圍: {min(auto_dates)} ~ {max(auto_dates)}\n")

        # ---- 人工 ----
        hrows = list(db.scalars(select(H).where(
            H.service_date.in_(auto_dates), H.pickup_time.is_not(None),
            H.pickup_lng.is_not(None), H.plate.is_not(None))).all())
        hvd = defaultdict(list)
        for r in hrows:
            hvd[(r.plate, r.service_date)].append({
                "t": mins(r.pickup_time), "dur": r.est_minutes,
                "lng": r.pickup_lng, "lat": r.pickup_lat,
                "dlng": r.dropoff_lng, "dlat": r.dropoff_lat})
        H_stat = analyze(hvd)

        # ---- 自動:auto_dispatch_stop 還原每趟(pickup+delivery 配 order_id)----
        arows = list(db.scalars(select(A).where(A.service_date.in_(auto_dates))).all())
        pick = {}   # (date,veh,oid) -> pickup stop
        drop = {}
        for s in arows:
            if not s.order_id:
                continue
            k = (s.service_date, s.vehicle_id, s.order_id)
            (pick if s.kind == "pickup" else drop)[k] = s
        avd = defaultdict(list)
        for k, ps in pick.items():
            d, veh, oid = k
            ds = drop.get(k)
            pt = mins(ps.eta)
            dt = mins(ds.eta) if ds else None
            dur = (dt - pt) if (dt is not None and pt is not None and dt > pt) else None
            avd[(veh, d)].append({
                "t": pt, "dur": dur, "lng": ps.lng, "lat": ps.lat,
                "dlng": ds.lng if ds else None, "dlat": ds.lat if ds else None})
        A_stat = analyze(avd)

        # ---- 往返同車% ----
        hby = defaultdict(list)
        for r in hrows:
            hby[r.service_date].append(r)
        hm, hs = roundtrip_same_vehicle(
            hby, lambda r, k: (r.pickup_lng, r.pickup_lat) if k == "p" else (r.dropoff_lng, r.dropoff_lat),
            lambda r: r.plate, lambda r: mins(r.pickup_time),
            lambda r: mins(r.dropoff_lng and 0), None)
        # 自動:用還原的每趟(含 pickup/drop 座標)
        aflat_by_date = defaultdict(list)
        for (veh, d), trips in avd.items():
            for t in trips:
                if t["lng"] is not None and t["dlng"] is not None:
                    aflat_by_date[d].append({**t, "veh": veh})
        am, asame = roundtrip_same_vehicle(
            aflat_by_date,
            lambda r, k: (r["lng"], r["lat"]) if k == "p" else (r["dlng"], r["dlat"]),
            lambda r: r["veh"], lambda r: r["t"], None, None)

        # ---- 輸出 ----
        def row(name, h, a, unit=""):
            hs_ = f"{h:.1f}{unit}" if isinstance(h, float) else f"{h}{unit}"
            as_ = f"{a:.1f}{unit}" if isinstance(a, float) else f"{a}{unit}"
            print(f"  {name:<22}{hs_:>14}{as_:>14}")

        print(f"  {'指標':<22}{'人工':>14}{'自動':>14}")
        print("  " + "-" * 50)
        row("總車日(用車數加總)", H_stat["veh_days"], A_stat["veh_days"])
        row("每日用車數(中位)", H_stat["veh_per_day_med"], A_stat["veh_per_day_med"])
        row("每車每日趟數(中位)", H_stat["tpvd_med"], A_stat["tpvd_med"])
        row("連續上車間距分(中位)", H_stat["gap_med"], A_stat["gap_med"])
        row("連續上車點距km(中位)", H_stat["hop_med"], A_stat["hop_med"])
        row("併車率%", H_stat["pool_pct"], A_stat["pool_pct"])
        print("  " + "-" * 50)
        print(f"  往返偵測:")
        print(f"    人工 可配對去程 {hm:,},回程同車 {100*hs/hm if hm else 0:.1f}%")
        print(f"    自動 可配對去程 {am:,},回程同車 {100*asame/am if am else 0:.1f}%")
    finally:
        db.close()


if __name__ == "__main__":
    main()
