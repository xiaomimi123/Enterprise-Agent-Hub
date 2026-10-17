"""员工端接入接口（/api/agent/*）：员工电脑上的接入器（agent/hub_agent.py）通过这里登录和领取配置。

- GET  /api/agent/config  公开：登录所需的 Casdoor 地址、client id、回调地址
- POST /api/agent/token   仅开发环境：账号密码登录（由中枢代为持有 agent 应用的 client secret）

生产环境的浏览器登录与续期由员工端直接和 Casdoor 完成（授权码 + PKCE，公开客户端，不需要密钥）。
中枢刻意不代换授权码：带着密钥换码时 Casdoor 对未带 PKCE 的授权码不做校验，被截获的授权码就可能被冒用。
- POST /api/agent/enroll  需 agent 令牌：返回该员工的模型 key、MCP 地址、岗位包内的技能全文，并记一条审计
"""

from __future__ import annotations

import uuid
from urllib.parse import unquote

import httpx
import jwt
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import content, db, policy
from .auth import _jwks_client
from .config import settings
from .newapi import NewApi, NewApiError, token_name

router = APIRouter(prefix="/api/agent", tags=["agent"])
LOOPBACK_REDIRECT = "http://127.0.0.1:27891/callback"


def _agent_client() -> tuple[str, str]:
    if not settings.agent_client_ids or not settings.agent_client_secret:
        raise HTTPException(503, "中枢尚未配置员工端 agent 应用，请先执行 make bootstrap")
    return settings.agent_client_ids[0], settings.agent_client_secret


@router.get("/config")
def config():
    client_id, _ = _agent_client()
    return {
        "org": settings.casdoor_org,
        "casdoor_url": settings.casdoor_public_url,
        "client_id": client_id,
        "redirect_uri": LOOPBACK_REDIRECT,
        "mcp_url": settings.mcp_public_url,
        "password_login": settings.agent_password_login,
    }


class PasswordLogin(BaseModel):
    username: str
    password: str


@router.post("/token")
def token(body: PasswordLogin):
    if not settings.agent_password_login:
        raise HTTPException(403, "账号密码登录未开启，请使用浏览器登录")
    client_id, secret = _agent_client()
    data = {"grant_type": "password", "client_id": client_id, "client_secret": secret,
            "username": body.username, "password": body.password, "scope": "openid profile"}
    r = httpx.post(f"{settings.casdoor_endpoint}/api/login/oauth/access_token", data=data, timeout=15).json()
    if not r.get("access_token"):
        raise HTTPException(401, f"登录失败：{r.get('error_description') or r.get('error') or '未知错误'}")
    return {k: r.get(k) for k in ("access_token", "refresh_token", "expires_in")}


def _verify_agent_token(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "未登录")
    tok = authorization.split(" ", 1)[1]
    try:
        key = _jwks_client().get_signing_key_from_jwt(tok)
        claims = jwt.decode(tok, key.key, algorithms=["RS256"], audience=list(settings.agent_client_ids),
                            options={"verify_iss": False})
    except jwt.PyJWTError:
        raise HTTPException(401, "登录凭证无效或已过期")
    if claims.get("owner") != settings.casdoor_org:
        raise HTTPException(403, "不属于本企业组织")
    return claims


@router.post("/enroll")
def enroll(authorization: str | None = Header(default=None), x_hub_trace_id: str | None = Header(default=None),
           x_hub_task: str | None = Header(default=None)):
    c = _verify_agent_token(authorization)
    dept = policy.dept_from_groups(c.get("groups"))
    p = policy.Principal(org=c["owner"], user_name=c["name"], display_name=c.get("displayName") or c["name"],
                         dept=dept, channel=policy.OFFICIAL)
    p.pack = policy.resolve_pack(p.org, p.user_name, dept)

    model = None
    na = NewApi()
    if na.configured and settings.default_model:
        try:
            model = {"base_url": f"{settings.newapi_public_url}/v1", "api_key": na.ensure_token(token_name(p.org, p.user_name)),
                     "model": settings.default_model}
        except NewApiError as e:
            raise HTTPException(502, str(e))

    allowed = set(p.pack["skills"]) if policy.can_use_tool(p, "skill.read") else set()
    skills = [{"id": s["id"], "name": s["name"], "description": s["description"], "content": content.read_skill(s["id"])}
              for s in content.list_skills() if s["id"] in allowed]

    # 接入器传来本次工作会话的追踪 ID，后面的 MCP 调用、出图、模型调用都挂在同一条链路上
    trace_id = (x_hub_trace_id or "").strip()[:64] or f"enroll-{uuid.uuid4().hex[:10]}"
    db.add_audit(trace_id=trace_id, org=p.org, user_name=p.user_name,
                 display_name=p.display_name, dept=dept, channel=p.channel, kind="登录", tool="agent.enroll",
                 detail=f"员工端领取配置：岗位包「{p.pack['name']}」，同步技能 {len(skills)} 个"
                        + ("，下发模型 key" if model else ""),
                 result="通过", summary=unquote(x_hub_task or "") or "员工端 agent 登录并同步配置")
    return {
        "employee": {"name": p.display_name, "user": p.user_name, "dept": dept, "role_pack": p.pack["name"]},
        "mcp_url": settings.mcp_public_url,
        "model": model,
        "skills": skills,
        "max_action_level": p.pack["max_action_level"],
    }
