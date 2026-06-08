"""地址簿檢視:門牌(校正後地址 + 座標)與其原始描述別名。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.address import AddressAlias, AddressPoint

router = APIRouter(prefix="/addresses", tags=["addresses"])


@router.get("")
def list_addresses(db: Session = Depends(get_db)):
    """列出所有門牌,附上對應的原始描述(別名)。"""
    points = list(db.scalars(select(AddressPoint).order_by(AddressPoint.id)).all())
    aliases = list(db.scalars(select(AddressAlias)).all())
    by_point: dict[int, list[str]] = {}
    misses: list[str] = []
    for a in aliases:
        if a.address_point_id is None:
            misses.append(a.raw_address)
        else:
            by_point.setdefault(a.address_point_id, []).append(a.raw_address)

    return {
        "points": [
            {
                "id": p.id,
                "standardized_address": p.standardized_address,
                "lng": p.lng,
                "lat": p.lat,
                "precision": p.precision,
                "city": p.city,
                "town": p.town,
                "source": p.source,
                "aliases": by_point.get(p.id, []),
                "alias_count": len(by_point.get(p.id, [])),
            }
            for p in points
        ],
        "unresolved_aliases": misses,
    }
