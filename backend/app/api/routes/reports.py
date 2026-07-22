"""營運報表彙總(需登入)。"""
import csv
import io
from datetime import date, timedelta, timezone

TW = timezone(timedelta(hours=8))

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.auto_dispatch_stop import AutoDispatchStop
from app.models.driver import Driver
from app.models.order import Order
from app.models.unassigned_record import UnassignedRecord
from app.models.vehicle import Vehicle

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user)])


@router.get("/overview")
def overview(
    date_from: date | None = None,
    date_to: date | None = None,
    source: str = "auto",   # auto=自動派遣結果(客戶回饋用,預設)/ human=人工實際指派
    db: Session = Depends(get_db),
):
    """區間營運彙總:狀態/車種分佈、每日量、派遣率、車輛使用。預設近 14 天。

    source=auto:讀自動派遣落地(auto_dispatch_stop + unassigned_record;需先跑對比 persist_day)。
    source=human:讀 orders 當前指派(done 日=人工實際結果)。
    """
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=13)
    common = {
        "vehicles_active": db.scalar(select(func.count()).select_from(Vehicle).where(Vehicle.active.is_(True))) or 0,
        "vehicles_total": db.scalar(select(func.count()).select_from(Vehicle)) or 0,
        "drivers": db.scalar(select(func.count()).select_from(Driver)) or 0,
    }
    if source == "auto":
        return _overview_auto(db, date_from, date_to, common)
    return _overview_human(db, date_from, date_to, common)


def _overview_human(db, date_from, date_to, common):
    o = Order

    def in_range(stmt):
        return stmt.where(o.service_date >= date_from, o.service_date <= date_to)

    total = db.scalar(in_range(select(func.count()).select_from(o))) or 0

    by_status = dict(
        db.execute(in_range(select(o.status, func.count()).group_by(o.status))).all()
    )
    by_vehicle_type = dict(
        db.execute(in_range(select(o.vehicle_type, func.count()).group_by(o.vehicle_type))).all()
    )

    # 每日:總數 / 已派 / 未派(未派 = 非 scheduled/ongoing/done/canceled,即仍 imported)
    rows = db.execute(
        in_range(
            select(
                o.service_date,
                func.count(),
                func.count().filter(o.assigned_vehicle_id.is_not(None)),
            ).group_by(o.service_date).order_by(o.service_date)
        )
    ).all()
    by_day = [
        {"date": d.isoformat(), "total": t, "assigned": a, "unassigned": t - a}
        for (d, t, a) in rows
    ]

    # 每車派遣量(區間內)
    veh_rows = db.execute(
        in_range(
            select(o.assigned_vehicle_id, func.count())
            .where(o.assigned_vehicle_id.is_not(None))
            .group_by(o.assigned_vehicle_id)
        )
    ).all()
    vehicle_names = dict(db.execute(select(Vehicle.id, Vehicle.plate)).all())
    per_vehicle = [
        {"vehicle_id": vid, "plate": vehicle_names.get(vid) or f"車#{vid}", "orders": cnt}
        for (vid, cnt) in veh_rows
    ]

    assigned = sum(v["orders"] for v in per_vehicle)

    dispatch_rate = round(assigned / total * 100, 1) if total else 0

    return {
        "source": "human",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "totals": {
            "orders": total, "assigned": assigned, "unassigned": total - assigned, **common,
        },
        "dispatch_rate": dispatch_rate,
        "by_status": by_status,
        "by_vehicle_type": by_vehicle_type,
        "by_day": by_day,
        "per_vehicle": per_vehicle,
    }


def _overview_auto(db, date_from, date_to, common):
    """自動派遣彙總:讀 auto_dispatch_stop(pickup=每張已派單)+ unassigned_record(未派)。"""
    S = AutoDispatchStop
    inr = lambda stmt: stmt.where(S.service_date >= date_from, S.service_date <= date_to)  # noqa: E731

    # 每日已派(pickup 去重 order_id)
    day_assigned = dict(db.execute(inr(
        select(S.service_date, func.count(func.distinct(S.order_id)))
        .where(S.kind == "pickup")).group_by(S.service_date)).all())
    # 每日未派(unassigned_record)
    U = UnassignedRecord
    day_unassigned = dict(db.execute(
        select(U.service_date, func.count())
        .where(U.service_date >= date_from, U.service_date <= date_to)
        .group_by(U.service_date)).all())

    days = sorted(set(day_assigned) | set(day_unassigned))
    by_day = [{"date": d.isoformat(), "assigned": day_assigned.get(d, 0),
               "unassigned": day_unassigned.get(d, 0),
               "total": day_assigned.get(d, 0) + day_unassigned.get(d, 0)} for d in days]

    assigned = sum(day_assigned.values())
    unassigned = sum(day_unassigned.values())
    total = assigned + unassigned

    # 每車派遣量(pickup 去重 order_id)
    veh_rows = db.execute(inr(
        select(S.vehicle_id, S.plate, func.count(func.distinct(S.order_id)))
        .where(S.kind == "pickup")).group_by(S.vehicle_id, S.plate)).all()
    per_vehicle = [{"vehicle_id": vid, "plate": plate or f"車#{vid}", "orders": cnt}
                   for (vid, plate, cnt) in sorted(veh_rows, key=lambda r: -r[2])]

    # 車種分佈(已派單 join orders)
    vt_rows = db.execute(inr(
        select(Order.vehicle_type, func.count(func.distinct(S.order_id)))
        .join(Order, Order.id == S.order_id)
        .where(S.kind == "pickup")).group_by(Order.vehicle_type)).all()
    by_vehicle_type = {k: v for k, v in vt_rows}

    return {
        "source": "auto",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "totals": {"orders": total, "assigned": assigned, "unassigned": unassigned, **common},
        "dispatch_rate": round(assigned / total * 100, 1) if total else 0,
        "by_status": {"scheduled": assigned, "imported": unassigned},   # 自動:已派/未派
        "by_vehicle_type": by_vehicle_type,
        "by_day": by_day,
        "per_vehicle": per_vehicle,
        "note": None if days else "此區間尚無自動派遣落地資料,請先於標準流程跑對比(persist_day)。",
    }


@router.get("/export-csv")
def export_csv(
    date_from: date | None = None,
    date_to: date | None = None,
    source: str = "auto",   # auto=自動派遣指派 / human=人工實際指派
    db: Session = Depends(get_db),
):
    """匯出區間訂單明細為 CSV（走 JWT，需 axios blob）。指派欄依 source 取自動或人工。"""
    if date_to is None:
        date_to = date.today()
    if date_from is None:
        date_from = date_to - timedelta(days=13)

    orders = list(db.scalars(
        select(Order)
        .where(Order.service_date >= date_from, Order.service_date <= date_to)
        .order_by(Order.service_date, Order.id)
    ).all())

    vehicle_names = dict(db.execute(select(Vehicle.id, Vehicle.plate)).all())

    # 自動派遣指派(order_id → 車牌/ETA/順序),取自 auto_dispatch_stop 的 pickup 列
    auto_map: dict[int, tuple] = {}
    if source == "auto":
        for oid, plate, eta, seq in db.execute(
            select(AutoDispatchStop.order_id, AutoDispatchStop.plate,
                   AutoDispatchStop.eta, AutoDispatchStop.seq)
            .where(AutoDispatchStop.service_date >= date_from,
                   AutoDispatchStop.service_date <= date_to,
                   AutoDispatchStop.kind == "pickup")).all():
            auto_map[oid] = (plate, eta, seq)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "訂單ID", "服務日期", "乘客姓名", "電話",
        "上車地址", "下車地址", "上車時間", "人數",
        "車種", "需輪椅", "允許共乘",
        "狀態", "指派車牌", "派遣順序", "ETA", "備註",
    ])
    for o in orders:
        if source == "auto":
            a = auto_map.get(o.id)
            plate = a[0] if a else ""
            status = "已派(自動)" if a else "未派(自動)"
            seq = a[2] if a else ""
            eta = a[1].astimezone(TW).strftime("%H:%M") if (a and a[1]) else ""
        else:
            plate = vehicle_names.get(o.assigned_vehicle_id, "") if o.assigned_vehicle_id else ""
            status = o.status
            seq = o.dispatch_seq or ""
            eta = o.eta.strftime("%H:%M") if o.eta else ""
        writer.writerow([
            o.id, o.service_date.isoformat(), o.passenger_name or "", o.passenger_phone or "",
            o.pickup_address, o.dropoff_address,
            o.pickup_time.strftime("%H:%M") if o.pickup_time else "",
            o.pax, o.vehicle_type,
            "是" if o.need_wheelchair else "否",
            "是" if o.allow_pool else "否",
            status, plate, seq, eta, o.note or "",
        ])

    buf.seek(0)
    filename = f"dr_fish_{'auto' if source == 'auto' else 'human'}_{date_from}_{date_to}.csv"
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),  # utf-8-sig 讓 Excel 正確顯示中文
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
