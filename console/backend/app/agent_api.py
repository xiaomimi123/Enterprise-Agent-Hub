"""员工端接入接口（/api/agent/*）：员工电脑上的接入器（agent/hub_agent.py）通过这里登录和领取配置。

- GET  /api/agent/config  公开：登录所需的 Casdoor 地址、client id、回调地址
- POST /api/agent/token   仅开发环境：账号密码登录（由中枢代为持有 agent 应用的 client secret）

生产环境的浏览器登录与续期由员工端直接和 Casdoor 完成（授权码 + PKCE，公开客户端，不需要密钥）。
中枢刻意不代换授权码：带着密钥换码时 Casdoor 对未带 PKCE 的授权码不做校验，被截获的授权码就可能被冒用。
- POST /api/agent/enroll  需 agent 令牌：返回该员工的模型 key、MCP 地址、岗位包内的技能全文，并记一条审计
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import unquote

import httpx
import jwt
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import accounts, app_access, apps, content, db, health, policy, skillstore, work
from .auth import _jwks_client
from .config import settings
from .newapi import SESSION_KEY_TTL, NewApi, NewApiError, plan_key, session_token_name, token_name

router = APIRouter(prefix="/api/agent", tags=["agent"])
LOOPBACK_REDIRECT = "http://127.0.0.1:27891/callback"


def _agent_client() -> tuple[str, str]:
    if not settings.agent_client_ids or not settings.agent_client_secret:
        raise HTTPException(503, "中枢尚未配置员工端 agent 应用，请先执行 make bootstrap")
    return settings.agent_client_ids[0], settings.agent_client_secret


@router.get("/hub_agent.py")
def agent_script():
    """员工端接入器脚本：公开下载（不含任何密钥），控制台「接入方式」页里给出下载链接。"""
    f = Path(settings.agent_dir) / "hub_agent.py"
    if not f.is_file():
        raise HTTPException(404, "中枢未挂载接入器脚本")
    return FileResponse(f, media_type="text/x-python; charset=utf-8", filename="hub_agent.py")


@router.get("/install.{kind}")
def install_script(kind: str):
    """一键接入脚本（Windows: install.ps1，macOS / Linux: install.sh），自动填好中枢地址，公开下载。"""
    if kind not in ("ps1", "sh"):
        raise HTTPException(404, "没有这个安装脚本")
    f = Path(settings.agent_dir) / f"install.{kind}"
    if not f.is_file():
        raise HTTPException(404, "中枢未挂载安装脚本")
    text = f.read_text(encoding="utf-8").replace("__HUB_URL__", settings.public_url.rstrip("/"))
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


def _agent_version() -> str:
    """中枢上挂载的接入器版本号（读脚本里的 VERSION = "x.y.z"），接入器据此决定要不要自动更新自己；读不到就返回空，不影响登录"""
    try:
        m = re.search(r'^VERSION = "([^"]+)"', (Path(settings.agent_dir) / "hub_agent.py").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


@router.get("/config")
def config():
    client_id, _ = _agent_client()
    return {
        "agent_version": _agent_version(),
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
    if not accounts.is_active(claims["owner"], claims.get("name", "")):
        raise HTTPException(401, "账号已被停用，请联系管理员")
    return claims


class Heartbeat(BaseModel):
    client: str = ""
    version: str = ""
    os: str = ""


@router.post("/heartbeat")
def heartbeat(body: Heartbeat, authorization: str | None = Header(default=None)):
    """接入器每分钟报到一次，控制台据此显示员工的 agent 是否在线、用的哪个 agent 和版本。"""
    c = _verify_agent_token(authorization)
    db.touch_presence(c["owner"], c["name"], client=body.client[:40], version=body.version[:20], os=body.os[:40])
    return {"ok": True}


class OpenApp(BaseModel):
    app_id: str


@router.post("/open-app")
def open_app_ticket(body: OpenApp, authorization: str | None = Header(default=None), x_hub_trace_id: str | None = Header(default=None)):
    """给不走 MCP 桥的客户端（如 hub_agent.py open-app）取启动凭证：权限与审计和 MCP 的 open_app 完全一样。"""
    c = _verify_agent_token(authorization)
    dept = policy.dept_from_groups(c.get("groups"))
    p = policy.Principal(org=c["owner"], user_name=c["name"], display_name=c.get("displayName") or c["name"],
                         dept=dept, channel=policy.OFFICIAL)
    p.pack = policy.resolve_pack(p.org, p.user_name, dept)
    trace_id = (x_hub_trace_id or "").strip()[:64] or f"app-{uuid.uuid4().hex[:10]}"
    try:
        return app_access.ticket_for(p, trace_id, body.app_id)
    except app_access.AppDenied as e:
        raise HTTPException(403, str(e))


class AppEvent(BaseModel):
    app_id: str
    version: str = ""
    ok: bool
    url: str = ""
    reason: str = ""
    missing: list[str] = []  # 已打开但缺少的能力（如「CodeBuddy CLI」「系统浏览器」），对应功能会被应用按能力禁用


@router.post("/app-event")
def app_event(body: AppEvent, authorization: str | None = Header(default=None), x_hub_trace_id: str | None = Header(default=None)):
    """接入器在本机启动应用后回报结果，中枢写审计（成功带网址，失败带原因）。"""
    c = _verify_agent_token(authorization)
    dept = policy.dept_from_groups(c.get("groups"))
    detail = (f"应用「{body.app_id}」v{body.version} 已在本机启动：{body.url[:80]}" if body.ok
              else f"应用「{body.app_id}」v{body.version} 启动失败：{body.reason[:200]}")
    missing = [m[:40] for m in body.missing[:8]]
    if body.ok and missing:
        detail += f"；缺少能力：{'、'.join(missing)}（对应功能不可用）"
    db.add_audit(trace_id=(x_hub_trace_id or "").strip()[:64] or f"app-{uuid.uuid4().hex[:10]}", org=c["owner"], user_name=c["name"],
                 display_name=c.get("displayName") or c["name"], dept=dept, channel=policy.OFFICIAL,
                 kind="应用", tool="app.launch", detail=detail, result="通过" if body.ok else "拒绝")
    return {"ok": True}


class WorkReportBody(BaseModel):
    app_id: str
    items: list[dict]


@router.post("/work-report")
def work_report(body: WorkReportBody, authorization: str | None = Header(default=None), x_hub_trace_id: str | None = Header(default=None)):
    """接入器把应用写在本机 outbox 里的成果转发到中枢。按 (人, 应用, key) 幂等，重复转发是更新。"""
    c = _verify_agent_token(authorization)
    if apps.get_app(body.app_id) is None:
        raise HTTPException(400, f"中枢没有注册应用「{body.app_id}」")
    p = policy.Principal(org=c["owner"], user_name=c["name"], display_name=c.get("displayName") or c["name"],
                         dept=policy.dept_from_groups(c.get("groups")), channel=policy.OFFICIAL)
    return work.report_batch(p, (x_hub_trace_id or "").strip()[:64] or f"work-{uuid.uuid4().hex[:10]}", f"应用:{body.app_id}", body.items)


class HealthBody(BaseModel):
    events: list  # 不限定元素类型：一条坏数据只跳过它自己，不让整批 422（接入器遇到 4xx 会丢掉整批）


@router.post("/health")
def app_health(body: HealthBody, authorization: str | None = Header(default=None)):
    """接入器转发本机记下的安装 / 登录 / 打开应用 / 运行结果（应用健康）。单批 ≤ 50 条，格式不对的条目跳过；每人每小时有上限。"""
    c = _verify_agent_token(authorization)
    if len(body.events) > health.MAX_BATCH:
        raise HTTPException(413, f"单批最多 {health.MAX_BATCH} 条")
    if not health.allow(c["owner"], c["name"], len(body.events)):
        raise HTTPException(429, "上报太频繁，稍后再试")
    events = [e for e in (health.clean(x) for x in body.events) if e]
    if not settings.database_url:
        return {"ok": True, "saved": 0, "skipped": len(body.events)}
    saved = db.add_health_events(c["owner"], c["name"], c.get("displayName") or c["name"], policy.dept_from_groups(c.get("groups")),
                                 events, health.RETENTION_DAYS)
    return {"ok": True, "saved": saved, "skipped": len(body.events) - saved}


@router.post("/enroll")
def enroll(authorization: str | None = Header(default=None), x_hub_trace_id: str | None = Header(default=None),
           x_hub_task: str | None = Header(default=None), x_hub_key_scope: str | None = Header(default=None)):
    c = _verify_agent_token(authorization)
    dept = policy.dept_from_groups(c.get("groups"))
    p = policy.Principal(org=c["owner"], user_name=c["name"], display_name=c.get("displayName") or c["name"],
                         dept=dept, channel=policy.OFFICIAL)
    p.pack = policy.resolve_pack(p.org, p.user_name, dept)

    # 岗位包选「自带模型」时，员工用自己 agent 的模型和积分，中枢不发模型 key
    model_mode = p.pack.get("model_mode") or "中枢模型"
    model = None
    na = NewApi() if model_mode == "中枢模型" else None
    if na and na.configured:
        try:
            base = token_name(p.org, p.user_name)
            # Hermes 会话（chat）用会话专属 key，key 名带追踪 ID，模型调用精确归属到这条链路；其余情况用基础 key
            session = x_hub_key_scope == "session" and bool((x_hub_trace_id or "").strip())
            name = session_token_name(p.org, p.user_name, x_hub_trace_id.strip()) if session else base
            if session:
                na.purge_expired_sessions(base)
            # 按岗位包限制 key 能用的模型和本月剩余额度（每次同步重算，跨月自动恢复；额度按基础 key + 全部会话 key 合计）
            plan = plan_key(p.pack.get("models") or [], na.available_models(), settings.default_model,
                            float(p.pack.get("monthly_quota") or 0), na.month_used_quota(base), settings.usd_cny)
            if plan["model"]:
                key = na.ensure_token(name, models=plan["models"], remain_quota=plan["remain_quota"], unlimited=plan["unlimited"],
                                      expires_in=SESSION_KEY_TTL if session else None)
                model = {"base_url": f"{settings.newapi_public_url}/v1", "api_key": key, "model": plan["model"],
                         "models": plan["models"] or [plan["model"]]}
        except NewApiError as e:
            raise HTTPException(502, str(e))

    allowed = set(p.pack["skills"]) if policy.can_use_tool(p, "skill.read") else set()
    skills = [{"id": s["id"], "name": s["name"], "description": s["description"], "content": skillstore.read_skill(s["id"])}
              for s in skillstore.list_skills() if s["id"] in allowed]

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
        "model_mode": model_mode,
        "skills": skills,
        "max_action_level": p.pack["max_action_level"],
        # 岗位包里能打开的应用：接入器据此在员工电脑上生成「打开某应用」的快捷方式（真正打开时仍逐次鉴权）
        "apps": [{"id": a["id"], "name": a["name"]} for a in app_access.list_for(p)],
    }
