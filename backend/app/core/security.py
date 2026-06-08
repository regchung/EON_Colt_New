"""密碼雜湊(PBKDF2)與 JWT(HS256),全用標準庫實作,免額外相依。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from app.core.config import settings

_PBKDF2_ROUNDS = 200_000


# --- 密碼 -------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), _PBKDF2_ROUNDS)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:  # noqa: BLE001
        return False


# --- JWT (HS256) ------------------------------------------------------------

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(message: str) -> str:
    sig = hmac.new(settings.SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return _b64url(sig)


def create_access_token(sub: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": sub, "exp": int(time.time()) + settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60}
    seg = _b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + \
        _b64url(json.dumps(payload, separators=(",", ":")).encode())
    return seg + "." + _sign(seg)


def decode_token(token: str) -> dict | None:
    try:
        h_seg, p_seg, sig = token.split(".")
        if not hmac.compare_digest(_sign(f"{h_seg}.{p_seg}"), sig):
            return None
        payload = json.loads(_b64url_decode(p_seg))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:  # noqa: BLE001
        return None
