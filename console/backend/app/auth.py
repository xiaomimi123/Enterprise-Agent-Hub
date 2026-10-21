"""控制台登录：Casdoor OAuth2 授权码流程。

1. 前端请求 /api/auth/login，拿到 Casdoor 授权地址并跳转（state 存在 httpOnly cookie 里防 CSRF）
2. Casdoor 登录后回到 /callback?code=...&state=...，前端把 code 和 state 交给 /api/auth/callback
3. 后端用 code 换取 access_token（JWT），校验签名后写入 httpOnly 会话 cookie
4. 之后每个请求都用 Casdoor 的公钥（JWKS）校验 cookie 里的 JWT，只允许组织管理员访问
"""

from __future__ import annotations

import re
import secrets
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from . import accounts, roles
from .config import settings

SESSION_COOKIE = "hub_session"
STATE_COOKIE = "hub_oauth_state"

router = APIRouter(prefix="/api/auth", tags=["auth"])
_jwks: jwt.PyJWKClient | None = None

DEMO_USER = {"name": "admin", "display_name": "管理员", "org": "demo", "title": "演示账号", "is_admin": True}


def _jwks_client() -> jwt.PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(f"{settings.casdoor_endpoint}/.well-known/jwks", cache_keys=True, lifespan=3600)
    return _jwks


def decode_token(token: str) -> dict:
    key = _jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(token, key.key, algorithms=["RS256"], audience=settings.casdoor_client_id,
                      options={"verify_iss": False})


def user_from_claims(c: dict) -> dict:
    return {
        "name": c.get("name"),
        "display_name": c.get("displayName") or c.get("name"),
        "org": c.get("owner"),
        "title": c.get("title") or "",
        "avatar": c.get("avatar") or "",
        "is_admin": bool(c.get("isAdmin")),
    }


def _authenticate(request: Request) -> dict:
    """校验登录会话（签名、有效期、本企业、账号未停用），返回用户。不判断角色。"""
    if not settings.auth_enabled:
        return DEMO_USER
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "未登录")
    try:
        claims = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "登录已过期")
    except jwt.PyJWTError:
        raise HTTPException(401, "登录凭证无效")
    user = user_from_claims(claims)
    if user["org"] != settings.casdoor_org:
        raise HTTPException(403, "不属于本企业组织")
    if not accounts.is_active(user["org"], user["name"]):
        raise HTTPException(401, "账号已被停用")
    return user


def current_user(request: Request) -> dict:
    """依赖项：只有管理员能过。成员、模型等管理接口显式用它，主管和老板进不去（默认拒绝）。"""
    user = _authenticate(request)
    if not user["is_admin"]:
        raise HTTPException(403, "只有组织管理员可以访问这个功能")
    return {**user, "role": roles.ADMIN, "depts": None}


# 老板 / 主管能访问的接口白名单（只读）；不在名单里的一律拒绝，新增接口默认只有管理员能用
_MANAGER_READ = (r"departments", r"members", r"role-packs", r"skills(?:/[^/]+)?", r"knowledge-bases(?:/[^/]+/documents)?", r"work/report")
_BOSS_READ = _MANAGER_READ + (r"overview", r"audit/traces(?:/[^/]+)?", r"usage", r"gpu/tasks", r"apps", r"catalog")
ROLE_ALLOWED = {roles.MANAGER: re.compile(r"^/api/(?:" + "|".join(_MANAGER_READ) + r")$"),
                roles.BOSS: re.compile(r"^/api/(?:" + "|".join(_BOSS_READ) + r")$")}


def console_user(request: Request) -> dict:
    """依赖项：管理员 / 老板 / 部门主管都能登录控制台，但老板和主管只能读白名单里的接口，且主管只看自己的部门。"""
    user = _authenticate(request)
    scope = roles.resolve(user["org"], user["name"], user["is_admin"]) if settings.auth_enabled else {"role": roles.ADMIN, "depts": None}
    if scope["role"] is None:
        raise HTTPException(403, "只有管理员、老板和部门主管可以访问控制台")
    if scope["role"] != roles.ADMIN and not (request.method == "GET" and ROLE_ALLOWED[scope["role"]].match(request.url.path)):
        raise HTTPException(403, "你的角色没有这个功能的权限")
    return {**user, **scope}


def console_user_for_me(request: Request) -> dict:
    """/me 不受白名单限制，只要有控制台角色就返回（带 role / depts，前端据此显示菜单）。"""
    user = _authenticate(request)
    scope = roles.resolve(user["org"], user["name"], user["is_admin"]) if settings.auth_enabled else {"role": roles.ADMIN, "depts": None}
    if scope["role"] is None:
        raise HTTPException(403, "只有管理员、老板和部门主管可以访问控制台")
    return {**user, **scope}


@router.get("/me")
def me(request: Request):
    return {"mode": settings.mode, "user": console_user_for_me(request)}


@router.get("/login")
def login(response: Response):
    if not settings.auth_enabled:
        raise HTTPException(400, "演示模式不需要登录")
    state = secrets.token_urlsafe(16)
    response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=settings.cookie_secure)
    query = urlencode({
        "client_id": settings.casdoor_client_id, "response_type": "code", "redirect_uri": settings.redirect_uri,
        "scope": "openid profile", "state": state,
    })
    return {"url": f"{settings.casdoor_public_url}/login/oauth/authorize?{query}"}


class CallbackBody(BaseModel):
    code: str
    state: str


@router.post("/callback")
def callback(body: CallbackBody, request: Request, response: Response):
    expected = request.cookies.get(STATE_COOKIE)
    if not expected or not secrets.compare_digest(expected, body.state):
        raise HTTPException(400, "登录状态校验失败，请重新登录")
    r = httpx.post(f"{settings.casdoor_endpoint}/api/login/oauth/access_token", timeout=10, data={
        "grant_type": "authorization_code", "code": body.code, "redirect_uri": settings.redirect_uri,
        "client_id": settings.casdoor_client_id, "client_secret": settings.casdoor_client_secret,
    })
    token = r.json().get("access_token")
    if not token:
        raise HTTPException(400, f"换取令牌失败：{r.json().get('error_description') or r.text[:200]}")
    try:
        claims = decode_token(token)
    except jwt.PyJWTError as e:
        raise HTTPException(400, f"令牌校验失败：{e}")
    user = user_from_claims(claims)
    max_age = max(60, int(claims.get("exp", 0)) - int(claims.get("iat", 0))) if claims.get("exp") else 86400
    response.delete_cookie(STATE_COOKIE)
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="lax", secure=settings.cookie_secure)
    return {"user": user}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    response.delete_cookie(SESSION_COOKIE)
    url = None
    if settings.auth_enabled and token:
        # 同时退出 Casdoor 的登录会话并作废令牌，否则下次会被自动登录
        url = f"{settings.casdoor_public_url}/api/logout?" + urlencode(
            {"id_token_hint": token, "post_logout_redirect_uri": settings.public_url})
    return {"ok": True, "casdoor_logout_url": url}
