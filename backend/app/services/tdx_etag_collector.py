"""TDX ETag 行程時間資料收集器。
每 5 分鐘取新北市即時 ETag 資料並存入 DB，
累積後可建立各時段歷史均值供預約制派遣調整矩陣使用。
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone, timedelta

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.tdx_etag_speed import TdxEtagSpeed

log = logging.getLogger(__name__)

TW = timezone(timedelta(hours=8))
_COLLECT_INTERVAL = 300  # 5 分鐘
_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _get_token() -> str | None:
    if not settings.TDX_CLIENT_ID or not settings.TDX_CLIENT_SECRET:
        return None
    try:
        r = requests.post(
            "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.TDX_CLIENT_ID,
                "client_secret": settings.TDX_CLIENT_SECRET,
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["access_token"]
    except Exception as e:
        log.warning(f"TDX token error: {e}")
        return None


def collect_once() -> int:
    """取一次新北市 ETag 即時資料存入 DB，回傳寫入筆數。"""
    token = _get_token()
    if not token:
        return 0
    try:
        r = requests.get(
            "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic/Live/ETag/City/NewTaipei?$format=JSON",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        pairs = data if isinstance(data, list) else data.get("ETagPairLives", [])

        now = datetime.now(TW)
        rows: list[TdxEtagSpeed] = []
        for pair in pairs:
            pid = pair.get("ETagPairID")
            if not pid:
                continue
            for flow in pair.get("Flows", []):
                spd = flow.get("SpaceMeanSpeed")
                tt = flow.get("TravelTime")
                vc = flow.get("VehicleCount")
                vtype = flow.get("VehicleType")
                rows.append(TdxEtagSpeed(
                    etag_pair_id=pid,
                    collected_at=now,
                    space_mean_speed=float(spd) if spd is not None and float(spd) > 0 else None,
                    travel_time=int(tt) if tt is not None and int(tt) > 0 else None,
                    vehicle_count=int(vc) if vc is not None and int(vc) >= 0 else None,
                    vehicle_type=int(vtype) if vtype is not None else None,
                ))

        if rows:
            db: Session = SessionLocal()
            try:
                db.add_all(rows)
                db.commit()
            finally:
                db.close()
        log.info(f"TDX ETag collected: {len(rows)} rows at {now.strftime('%H:%M')}")
        return len(rows)
    except Exception as e:
        log.warning(f"TDX ETag collect error: {e}")
        return 0


def _run_loop():
    log.info("TDX ETag collector started (interval=5min)")
    while not _stop_event.is_set():
        try:
            collect_once()
        except Exception as e:
            log.error(f"TDX collector loop error: {e}")
        _stop_event.wait(timeout=_COLLECT_INTERVAL)
    log.info("TDX ETag collector stopped")


def start():
    """啟動背景收集執行緒（FastAPI lifespan 呼叫）。"""
    global _thread
    if not settings.TDX_CLIENT_ID:
        log.info("TDX_CLIENT_ID 未設定，跳過 ETag 收集器")
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run_loop, daemon=True, name="tdx-etag-collector")
    _thread.start()


def stop():
    """停止背景執行緒（FastAPI shutdown 呼叫）。"""
    _stop_event.set()
    if _thread:
        _thread.join(timeout=5)
