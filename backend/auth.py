"""Single-workspace login with opaque, revocable server-side sessions."""

import hashlib
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .config import settings

router = APIRouter(prefix="/api/v1/auth")
COOKIE = "framecraft_session"
sessions: dict[str, tuple[str, float]] = {}
attempts: dict[str, list[float]] = {}


def session_user(request: Request):
    key = hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest()
    session = sessions.get(key)
    if session and session[1] > time.time():
        return session[0]
    sessions.pop(key, None)
    return None


class Credentials(BaseModel):
    username: str = Field(max_length=128)
    password: str = Field(max_length=1024)


@router.post("/login")
def login(value: Credentials, request: Request, response: Response):
    if not settings.auth_password:
        raise HTTPException(503, "管理员尚未配置登录密码，请在后端设置 AUTH_PASSWORD 并重启服务")
    now = time.time()
    for key in list(attempts):
        attempts[key] = [t for t in attempts[key] if t > now - 300]
        if not attempts[key]:
            del attempts[key]
    host = request.client.host if request.client else "unknown"
    failures = attempts.get(host, [])
    if len(failures) >= 10:
        raise HTTPException(429, "登录尝试过多，请 5 分钟后重试")
    valid_user = secrets.compare_digest(value.username.encode(), settings.auth_username.encode())
    valid_password = secrets.compare_digest(value.password.encode(), settings.auth_password.encode())
    if not (valid_user and valid_password):
        attempts[host] = [*failures, now]
        raise HTTPException(401, "用户名或密码错误")
    attempts.pop(host, None)
    for key, session in list(sessions.items()):
        if session[1] <= now:
            del sessions[key]
    old_key = hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest()
    sessions.pop(old_key, None)
    token = secrets.token_urlsafe(32)
    lifetime = settings.auth_session_hours * 3600
    sessions[hashlib.sha256(token.encode()).hexdigest()] = (settings.auth_username, now + lifetime)
    response.set_cookie(
        COOKIE,
        token,
        max_age=lifetime,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    return {"username": settings.auth_username}


@router.get("/me")
def me(request: Request):
    username = session_user(request)
    if not username:
        raise HTTPException(401, "请先登录")
    return {"username": username}


@router.post("/logout")
def logout(request: Request, response: Response):
    key = hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest()
    sessions.pop(key, None)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
