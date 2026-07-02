"""訂單/未派診斷小工具 —— 一律以台灣時間顯示,避免時區誤判。

用法(在 backend 容器內執行):
    docker compose exec backend python -m scripts.show_order 47191
    docker compose exec backend python -m scripts.show_order --date 2026-06-24 --unassigned
    docker compose exec backend python -m scripts.show_order --date 2026-06-24 --fleet 神同行

刻意用「顯式 astimezone(TW)」印時間(勿用無參 astimezone(),那會跟容器時區走)。
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.order import Order
from app.models.vehicle import Vehicle

TW = timezone(timedelta(hours=8))


def _tw(dt: datetime | None) -> str:
    return dt.astimezone(TW).strftime("%Y-%m-%d %H:%M (台)") if dt else "—"


def _line(o: Order, db) -> str:
    plate = ""
    if o.assigned_vehicle_id:
        v = db.get(Vehicle, o.assigned_vehicle_id)
        plate = f" → {v.plate if v else o.assigned_vehicle_id}"
        if o.support_fleet and o.support_fleet != o.fleet:
            plate += f"(支援·{o.support_fleet})"
    wf = "福" if (o.vehicle_type == "welfare" or o.need_wheelchair) else "一般"
    return (f"#{o.id} {_tw(o.pickup_time)} {o.passenger_name or '—'} "
            f"[{o.fleet or '未標'}/{wf}/{o.status}]{plate}\n"
            f"    {o.pickup_address} → {o.dropoff_address}")


def main() -> None:
    ap = argparse.ArgumentParser(description="以台灣時間顯示訂單(診斷用)")
    ap.add_argument("order_id", nargs="?", type=int, help="單筆訂單 id")
    ap.add_argument("--date", help="服務日期 YYYY-MM-DD")
    ap.add_argument("--fleet", help="車行過濾")
    ap.add_argument("--unassigned", action="store_true", help="只列未派(imported)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.order_id:
            o = db.get(Order, args.order_id)
            print(_line(o, db) if o else f"找不到訂單 #{args.order_id}")
            return
        if not args.date:
            ap.error("請給 order_id 或 --date")
        q = select(Order).where(Order.service_date == date.fromisoformat(args.date))
        if args.fleet:
            q = q.where(Order.fleet == args.fleet)
        if args.unassigned:
            q = q.where(Order.status == "imported")
        rows = list(db.scalars(q.order_by(Order.pickup_time)).all())
        print(f"{args.date}{' · ' + args.fleet if args.fleet else ''}"
              f"{' · 未派' if args.unassigned else ''}:{len(rows)} 筆")
        for o in rows:
            print(_line(o, db))
    finally:
        db.close()


if __name__ == "__main__":
    main()
