"""共用相依:目前登入使用者(JWT Bearer)。"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if cred is None:
        raise HTTPException(status_code=401, detail="未提供憑證")
    payload = decode_token(cred.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="憑證無效或已過期")
    return payload["sub"]
