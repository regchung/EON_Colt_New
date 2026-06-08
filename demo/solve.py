#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SmartCar 派遣 demo（pyvroom 版,免 Docker / 免 OSRM）

讀 matrix-mode.json 的「自帶 durations 矩陣 + shipments + skills + capacity + time_window」,
呼叫 VROOM 引擎求解,印出每台車的派遣順序。

用法:  python3 solve.py
"""
import json
import os
import numpy as np
import pandas as pd
import vroom

HERE = os.path.dirname(os.path.abspath(__file__))


def hms(sec: int) -> str:
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def main():
    with open(os.path.join(HERE, "matrix-mode.json"), encoding="utf-8") as f:
        data = json.load(f)

    loc_names = data["_locations"]
    problem = vroom.Input()

    # 1) 設定自帶行駛時間矩陣(profile = "car")
    durations = data["matrices"]["car"]["durations"]
    problem.set_durations_matrix("car", np.array(durations, dtype=np.uint32))

    # 2) 車輛(含 skills / capacity / 上下班時間窗)
    for v in data["vehicles"]:
        problem.add_vehicle(vroom.Vehicle(
            id=v["id"],
            start=v["start_index"],
            end=v["end_index"],
            profile=v["profile"],
            capacity=v["capacity"],
            skills=set(v.get("skills", [])),
            time_window=vroom.TimeWindow(v["time_window"][0], v["time_window"][1]),
        ))

    # 3) 訂單 = shipment(上車 pickup → 下車 delivery,綁同一台車)
    for s in data["shipments"]:
        p, d = s["pickup"], s["delivery"]
        pickup = vroom.ShipmentStep(
            id=p["id"], location=p["location_index"],
            service=p.get("service", 0),
            time_windows=[vroom.TimeWindow(a, b) for a, b in p.get("time_windows", [])],
        )
        delivery = vroom.ShipmentStep(
            id=d["id"], location=d["location_index"],
            service=d.get("service", 0),
            time_windows=[vroom.TimeWindow(a, b) for a, b in d.get("time_windows", [])],
        )
        problem.add_shipment(
            pickup, delivery,
            amount=vroom.Amount(s.get("amount", [0])),
            skills=set(s.get("skills", [])),
            priority=s.get("priority", 0),
        )

    sol = problem.solve(exploration_level=5, nb_threads=4)

    print("=" * 64)
    print("SmartCar 派遣結果")
    print("=" * 64)
    print(f"未派遣訂單數 : {sol.summary.unassigned}")
    print(f"總行駛時間   : {hms(sol.summary.duration)}  ({sol.summary.duration}s)")
    print()

    veh_desc = {v["id"]: v["description"] for v in data["vehicles"]}
    # 各 step 的載客增減(pickup +amount,delivery -amount),用來顯示車上即時人數
    delta = {}
    for s in data["shipments"]:
        amt = s.get("amount", [0])[0]
        delta[s["pickup"]["id"]] = amt
        delta[s["delivery"]["id"]] = -amt

    for vid, grp in sol.routes.groupby("vehicle_id"):
        print(f"▶ 車輛 {vid}（{veh_desc.get(vid, '')}）")
        load = 0
        for _, step in grp.iterrows():
            loc = step["location_index"]
            name = loc_names.get(str(int(loc)), "") if not pd.isna(loc) else ""
            jid = step["id"]
            if not pd.isna(jid):
                load += delta.get(int(jid), 0)
            jid_s = "" if pd.isna(jid) else f" job#{int(jid)}"
            print(f"    [{step['type']:<8}] 到達 {hms(step['arrival'])}  車上 {load} 人  {name}{jid_s}")
        print()


if __name__ == "__main__":
    main()
