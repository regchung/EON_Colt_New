#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從執行中的 API 組裝 /tmp/report_data.json(供 make_report.py 產 PDF)。

來源:/dispatch/comparison/summary、/dispatch/comparison(top)、/dispatch/pool-gain、
/history/stats、/vehicles、/drivers、/addresses。需後端在 localhost:8000 運行。
"""
import json
import urllib.request

BASE = "http://localhost:8000/api"


def _req(method, path, token=None, data=None):
    url = BASE + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


tok = _req("POST", "/auth/login", data={"username": "admin", "password": "admin123"})["access_token"]
summary = _req("GET", "/dispatch/comparison/summary", tok)
top = _req("GET", "/dispatch/comparison?limit=10", tok)
try:
    pool = _req("GET", "/dispatch/pool-gain", tok)
    pool = pool if pool.get("available") else None
except Exception:
    pool = None

hist = _req("GET", "/history/stats", tok)
vehicles = _req("GET", "/vehicles", tok)
drivers = _req("GET", "/drivers", tok)
addresses = _req("GET", "/addresses", tok)

total_orders = hist.get("total", 0)
done = summary["group"]["orders"]
overview = f"{total_orders}|{done}|{len(vehicles)}|{len(drivers)}|{len(addresses)}"

out = {"summary": summary, "top_days": top, "overview": overview, "pool_gain": pool}
with open("/tmp/report_data.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

g = summary["group"]
print("report_data.json 已產生")
print(f"  車行: {list(summary['by_fleet'])}")
print(f"  集團: {g['human_vehicle_days']}→{g['vroom_vehicle_days']} 車日 (↓{g['saved_pct']}%), "
      f"{g['days_vroom_better']}/{g['days']} 天自動更省")
print(f"  overview: {overview}")
if pool:
    print(f"  共乘增益: v_now={pool['group']['v_now']} v_pool={pool['group']['v_pool']}")
