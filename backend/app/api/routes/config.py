"""前端執行期設定(例如地圖金鑰)。Map8 金鑰本即為前端地圖用 token。"""
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/config", tags=["config"])

MAP8_STYLE = "https://api.map8.zone/styles/go-life-maps-tw-style-std/style.json"


@router.get("")
def get_config() -> dict:
    return {
        "map8_key": settings.MAP8_API_KEY,
        "map8_style": MAP8_STYLE,
        "has_map": bool(settings.MAP8_API_KEY),
    }
