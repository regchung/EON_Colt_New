"""衝突剔除 + 補排一體化服務。

流程：
  1. schedule_validator.validate() → 取衝突清單
  2. 每個衝突對的「後趟」(nxt) 改回 imported + 清空 assigned_vehicle_id
  3. unscheduled_assigner.assign() 對剔除訂單嘗試補排
  4. 回傳：被剔除清單 / 補排成功 / 補排失敗

dry_run=True：全程不 commit，用 flush + rollback 模擬。
"""
from __future__ import annotations

from datetime import date, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.vehicle import Vehicle
from app.services import schedule_validator
from app.services import unscheduled_assigner

TW = timezone(timedelta(hours=8))


def resolve(
    db: Session,
    service_date: date,
    late_tolerance_min: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    回傳 {
      "unassigned_from_conflicts": [ {order_id, passenger, pickup_time, vehicle_was, conflict_type} ],
      "reassigned":                [ {order_id, passenger, pickup_time, vehicle, detour_km, ...} ],
      "still_unassigned":          [ {order_id, passenger, pickup_time, reason} ],
      "violations_detail":         [ ...原始衝突清單... ],
      "summary": { conflicts_found, unassigned, reassigned, still_unassigned, dry_run }
    }
    """
    # 1. 取衝突清單（含道路事件，一次呼叫）
    validation = schedule_validator.validate(db, service_date)
    violations = validation.get("violations", [])

    if not violations:
        return {
            "unassigned_from_conflicts": [],
            "reassigned": [],
            "still_unassigned": [],
            "violations_detail": [],
            "summary": {
                "conflicts_found": 0,
                "unassigned": 0,
                "reassigned": 0,
                "still_unassigned": 0,
                "dry_run": dry_run,
            },
        }

    # 2. 收集需剔除的 nxt 訂單 ID（去重；同一訂單可能出現在多個衝突對中）
    nxt_ids: set[int] = set()
    conflict_type_map: dict[int, str] = {}
    for v in violations:
        oid = v["nxt"]["order_id"]
        nxt_ids.add(oid)
        # 若同一訂單被多個衝突引用，取最嚴重的類型（roundtrip > overlap）
        prev = conflict_type_map.get(oid, "overlap")
        conflict_type_map[oid] = "roundtrip" if (v["type"] == "roundtrip" or prev == "roundtrip") else "overlap"

    # 取訂單 + 原指派車輛資料
    nxt_orders: list[Order] = list(db.scalars(
        select(Order).where(Order.id.in_(nxt_ids))
    ).all())

    vids = {o.assigned_vehicle_id for o in nxt_orders if o.assigned_vehicle_id}
    vmap: dict[int, Vehicle] = {}
    if vids:
        vmap = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(vids))).all()}

    unassigned_list = [
        {
            "order_id":     o.id,
            "passenger":    o.passenger_name,
            "pickup_time":  o.pickup_time.astimezone(TW).strftime("%H:%M") if o.pickup_time else None,
            "vehicle_was":  vmap[o.assigned_vehicle_id].plate if o.assigned_vehicle_id in vmap else None,
            "conflict_type": conflict_type_map.get(o.id, "overlap"),
        }
        for o in nxt_orders
    ]

    # 3. 剔除（改回 imported）+ 補排
    if dry_run:
        # flush 讓 assign 能在同一 session 內看到 imported 狀態，最後 rollback 還原
        for o in nxt_orders:
            o.assigned_vehicle_id = None
            o.status = "imported"
        db.flush()
        assign_result = unscheduled_assigner.assign(
            db, service_date, max_detour_km=15.0,
            late_tolerance_min=late_tolerance_min, dry_run=True,
        )
        db.rollback()
    else:
        for o in nxt_orders:
            o.assigned_vehicle_id = None
            o.status = "imported"
        db.commit()
        assign_result = unscheduled_assigner.assign(
            db, service_date, max_detour_km=15.0,
            late_tolerance_min=late_tolerance_min, dry_run=False
        )

    return {
        "unassigned_from_conflicts": unassigned_list,
        "reassigned":                assign_result["assigned"],
        "still_unassigned":          assign_result["still_unassigned"],
        "violations_detail":         violations,
        "summary": {
            "conflicts_found": len(violations),
            "unassigned":      len(nxt_ids),
            "reassigned":      assign_result["summary"]["assigned"],
            "still_unassigned": assign_result["summary"]["unassigned"],
            "dry_run":         dry_run,
        },
    }
