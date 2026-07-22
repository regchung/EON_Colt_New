#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""匯入固定行程資料"""
import sys, os
sys.path.insert(0, "/app")

from app.db.session import SessionLocal
from app.models.fixed_route import FixedRoute
from sqlalchemy import delete

db = SessionLocal()
db.execute(delete(FixedRoute))
db.commit()

routes = [
    # 小驢駒（有固定起訖地址）
    dict(label="小驢駒先生A", driver_name="葉遠雄", time_slot="全天",
         pickup_address="鶯歌區永智街39號", dropoff_address="林口區文化北路一段425號",
         match_name="小驢駒先生A", pax=1),
    dict(label="小驢駒先生B", driver_name="李其諺", time_slot="全天",
         pickup_address="蘆竹區山林路一段195號", dropoff_address="林口區文化北路一段425號",
         match_name="小驢駒先生B", pax=1),
    dict(label="小驢駒先生C", driver_name="何柏霖", time_slot="全天",
         pickup_address="三重區中華路105號", dropoff_address="林口區文化北路一段425號",
         match_name="小驢駒先生C", pax=1),
    dict(label="小驢駒先生D", driver_name="李鑄", time_slot="全天",
         pickup_address="新店區中央路133巷18號", dropoff_address="林口區文化北路一段425號",
         match_name="小驢駒先生D", pax=1),
    dict(label="小驢駒先生E", driver_name="陳德賢", time_slot="全天",
         pickup_address="板橋區合宜一路57號", dropoff_address="林口區文化北路一段425號",
         match_name="小驢駒先生E", pax=1),
    dict(label="小驢駒先生F", driver_name="皮天辰", time_slot="全天",
         pickup_address="樹林區中華路341號", dropoff_address="林口區文化北路一段425號",
         match_name="小驢駒先生F", pax=1),
    dict(label="小驢駒先生G", driver_name="董巍", time_slot="全天",
         pickup_address="板橋區中正路325巷47號", dropoff_address="林口區文化北路一段425號",
         match_name="小驢駒先生G", pax=1),
    dict(label="小驢駒先生J", driver_name="朱鐵軍", time_slot="全天",
         pickup_address="龜山區樂學路105號", dropoff_address="林口區文化北路一段425號",
         match_name="小驢駒先生J", pax=1),
    # 學校 / 機構（靠訂單乘客姓名比對）
    dict(label="北投國小",       driver_name="林治圻",  time_slot="全天", match_name="北投國小"),
    dict(label="成德國中-1",     driver_name="梁銘漢",  time_slot="全天", match_name="成德國中-1"),
    dict(label="成德國中-2(早)", driver_name="吳奇龍",  time_slot="早",   match_name="成德國中-2"),
    dict(label="成德國中-2(下午)", driver_name="林泰吉", time_slot="午後", match_name="成德國中-2"),
    dict(label="南港國小",       driver_name="謝美玲",  time_slot="全天", match_name="南港國小"),
    dict(label="基隆日照",       driver_name="陳信忠",  time_slot="全天", match_name="基隆日照"),
    dict(label="潭美國小-1",     driver_name="王俊凱",  time_slot="全天", match_name="潭美國小-1"),
    dict(label="潭美國小-2",     driver_name="周易淳",  time_slot="全天", match_name="潭美國小-2"),
    dict(label="百齡高中-1",     driver_name="李偉豪",  time_slot="全天", match_name="百齡高中-1"),
    dict(label="百齡高中-2",     driver_name="林錦賜",  time_slot="全天", match_name="百齡高中-2"),
    dict(label="萬里錸工廠(早晚)", driver_name="蔡耀棟", time_slot="早晚", keyword="錸工廠", match_name="萬里錸工廠"),
    dict(label="萬里錸工廠(中午)", driver_name="陳信忠", time_slot="午",   keyword="錸工廠", match_name="萬里錸工廠"),
    dict(label="向怡診所",       driver_name="羅仰暉",  time_slot="全天", match_name="向怡診所"),
    dict(label="文山特教",       driver_name="吳奇龍",  time_slot="全天", match_name="文山特教"),
]

for r in routes:
    db.add(FixedRoute(
        label=r["label"],
        driver_name=r["driver_name"],
        time_slot=r.get("time_slot", "全天"),
        keyword=r.get("keyword"),
        match_name=r.get("match_name"),
        pickup_address=r.get("pickup_address"),
        dropoff_address=r.get("dropoff_address"),
        pax=r.get("pax", 1),
        vehicle_type="normal",
        active=True,
    ))

db.commit()
print(f"完成：寫入 {len(routes)} 筆固定行程")
