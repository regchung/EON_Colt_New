#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""營運分析報告的資料收集器(容器端,需 DB)。

用法(在後端容器內跑,輸出 JSON 到 stdout):
  docker compose exec -T backend python - < scripts/ops_report_collect.py > /tmp/ops_report_data.json
再由 scripts/make_ops_report.py(本機 reportlab)讀此 JSON 產 PDF。
"""
import json
import statistics
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.dispatch_history import DispatchHistory as DH
from app.models.order import Order
from app.services import unassigned_insights as ui

WD = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


def main():
    db = SessionLocal()
    out = {}

    rng = db.execute(select(func.min(DH.service_date), func.max(DH.service_date), func.count())).one()
    out["range"] = {"start": str(rng[0]), "end": str(rng[1]), "total": rng[2]}

    rows = db.execute(select(
        DH.service_date, DH.pickup_time, DH.pickup_city, DH.pickup_town,
        DH.plate, DH.distance_m, DH.est_minutes,
    )).all()

    # 時間①：weekday 日均趟次/車數
    d_days = defaultdict(set); d_trips = Counter(); d_dayplate = defaultdict(lambda: defaultdict(set))
    for sd, pt, city, town, plate, dist, est in rows:
        wd = sd.weekday(); d_days[wd].add(sd); d_trips[wd] += 1
        if plate:
            d_dayplate[wd][sd].add(plate)
    out["weekday"] = [{
        "name": WD[wd], "days": len(d_days[wd]),
        "avg_trips": round(d_trips[wd] / len(d_days[wd]), 1) if d_days[wd] else 0,
        "avg_veh": round(sum(len(p) for p in d_dayplate[wd].values()) / len(d_days[wd])) if d_days[wd] else 0,
    } for wd in range(7)]

    # 時間②：上車時段分布
    hr = Counter()
    for sd, pt, *_ in rows:
        if pt:
            hr[pt.hour] += 1
    toth = sum(hr.values())
    out["hour"] = [{"h": h, "n": hr.get(h, 0), "pct": round(hr.get(h, 0) / toth * 100, 1)} for h in range(6, 19)]
    out["out_of_hours_pct"] = round(sum(v for h, v in hr.items() if h < 6 or h >= 18) / toth * 100, 1)
    out["peak_hour"] = max(hr, key=hr.get)

    # 時間③：尖峰壅塞情報(隱含時速 = 距離/估時,各時段中位)
    sp_hour = defaultdict(list); allsp = []
    for sd, pt, city, town, plate, dist, est in rows:
        if pt and dist and est and dist > 300 and est > 1:
            kmh = (dist / 1000) / (est / 60)
            if 2 <= kmh <= 90:
                sp_hour[pt.hour].append(kmh); allsp.append(kmh)
    day_med = statistics.median(allsp) if allsp else 0
    speed_rows = []
    for h in range(6, 19):
        v = sp_hour.get(h, [])
        if not v:
            continue
        med = statistics.median(v)
        speed_rows.append({
            "h": h, "kmh": round(med, 1),
            "slower_pct": round((day_med - med) / day_med * 100) if day_med else 0,
            "share_pct": round(hr.get(h, 0) / toth * 100, 1),
        })
    slow = [r for r in speed_rows if r["slower_pct"] >= 25 and r["share_pct"] >= 1]
    out["congestion"] = {
        "day_median_kmh": round(day_med, 1),
        "speed_by_hour": speed_rows,
        "slow_hours": slow,
        "slow_share_pct": round(sum(r["share_pct"] for r in slow), 1),
    }

    # 區域①：縣市
    cty = Counter()
    for sd, pt, city, town, plate, dist, est in rows:
        cty[(city or "其他").replace("臺", "台")] += 1
    totc = sum(cty.values())
    out["city"] = [{"name": c, "n": n, "pct": round(n / totc * 100, 1)} for c, n in cty.most_common(5)]
    twn = Counter()
    for sd, pt, city, town, plate, dist, est in rows:
        if town:
            twn[((city or "").replace("臺", "台")) + town] += 1
    out["town_top"] = [{"name": t, "n": n, "pct": round(n / totc * 100, 1)} for t, n in twn.most_common(8)]
    vt = defaultdict(Counter)
    for sd, pt, city, town, plate, dist, est in rows:
        if plate and town:
            vt[plate][town] += 1
    ratios = sorted(max(c.values()) / sum(c.values()) for c in vt.values() if sum(c.values()) >= 30)
    out["zone_signal"] = {
        "vehicles": len(ratios),
        "median_pct": round(statistics.median(ratios) * 100) if ratios else 0,
        "ge50": sum(1 for r in ratios if r >= 0.5),
    }

    # 未派:歷史回測聚合
    agg = ui.aggregate(db)
    out["unassigned_hist"] = {"total": agg["total"],
                              "by_reason": {k: v for k, v in agg["by_reason_label"].items() if v}}

    # 未派:6/22 實派
    imp = db.execute(select(Order.pickup_time, Order.passenger_name, Order.pax,
                            Order.vehicle_type, Order.need_wheelchair)
                     .where(Order.service_date == date(2026, 6, 22), Order.status == "imported")).all()
    live = [{"t": pt.strftime("%H:%M") if pt else "", "name": nm or "",
             "pax": pax or 1, "welfare": (vt_ == "welfare" or bool(wc))}
            for pt, nm, pax, vt_, wc in imp]
    out["unassigned_live"] = {"date": "2026-06-22", "total": len(live),
                              "pax": sum(x["pax"] for x in live), "items": live}

    db.close()
    print(json.dumps(out, ensure_ascii=False))


main()
