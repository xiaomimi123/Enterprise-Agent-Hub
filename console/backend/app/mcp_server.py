"""中枢 MCP Server：员工的 agent（以及经授权的外部智能体）通过它使用技能和知识库。

运行：uv run uvicorn app.mcp_server:app --port 8200
地址：http://<中枢>:8200/mcp（Streamable HTTP），请求头带 Authorization: Bearer <Casdoor 令牌>

- 身份：令牌由 Casdoor 签发，按签发它的应用区分入口——官方 agent 应用 = 「官方 agent」，外部应用 = 「外部智能体」
- 权限：每次调用都按员工的岗位包判断（policy.py），提示词无法绕过
- 审计：每次调用写一条审计事件；同一 MCP 会话共用一个 trace_id（也可用请求头 X-Hub-Trace-Id 指定），
  请求头 X-Hub-Task 可以带上任务描述（URL 编码），显示在控制台审计日志里
"""

from __future__ import annotations

import json
import time
from urllib.parse import unquote

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer

from . import content, db, gpu, policy
from .auth import _jwks_client
from .config import settings
from .content import KB_BY_NAME, KB_REGISTRY

INSTRUCTIONS = """这是企业智能体中枢。你可以：
- whoami：查看当前员工身份和岗位包
- list_skills / read_skill：读取岗位包内的技能（SKILL.md），按技能里的步骤完成工作
- search_knowledge：检索有权限的企业知识库
- generate_cover / get_cover_task：派发到公司 GPU 节点生成封面图（排队执行）
权限由中枢按员工岗位包强制执行，被拒绝时请如实告知员工，不要尝试绕过。"""


_last_touch: dict[str, float] = {}


def _touch(claims: dict, client_id: str) -> None:
    """记录员工端活跃时间（控制台据此显示在线 agent）。同一员工 60 秒内只写一次库。"""
    if client_id not in settings.agent_client_ids:
        return
    key = f"{claims.get('owner')}/{claims.get('name')}"
    if time.time() - _last_touch.get(key, 0) < 60:
        return
    _last_touch[key] = time.time()
    try:
        db.touch_presence(claims["owner"], claims["name"], policy.dept_from_groups(claims.get("groups")))
    except Exception:  # noqa: BLE001 在线状态是附加信息，写库失败不影响调用
        pass


class CasdoorTokenVerifier:
    """校验 Casdoor 签发的 JWT：签名、有效期、受众必须是中枢认可的 agent 应用。"""

    async def verify_token(self, token: str) -> AccessToken | None:
        audiences = [*settings.agent_client_ids, *settings.external_client_ids]
        if not audiences:
            return None
        try:
            key = _jwks_client().get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=audiences, options={"verify_iss": False})
        except jwt.PyJWTError:
            return None
        if claims.get("owner") != settings.casdoor_org:
            return None
        aud = claims.get("aud")
        client_id = next((a for a in (aud if isinstance(aud, list) else [aud]) if a in audiences), "")
        _touch(claims, client_id)
        return AccessToken(token=token, client_id=client_id, scopes=[], expires_at=claims.get("exp"),
                           subject=claims.get("sub"), claims=claims)


mcp = MCPServer(
    name="hub",
    title="企业智能体中枢",
    instructions=INSTRUCTIONS,
    version="0.1.0",
    token_verifier=CasdoorTokenVerifier(),
    auth=AuthSettings(issuer_url=settings.casdoor_public_url or "http://localhost:8000",
                      resource_server_url=settings.mcp_public_url,
                      # 受众（签发应用）已在 CasdoorTokenVerifier 中校验
                      validate_token_resource=False),
)


def _principal() -> policy.Principal:
    tok = get_access_token()
    if tok is None or not tok.claims:
        raise PermissionError("未认证")
    c = tok.claims
    channel = policy.OFFICIAL if tok.client_id in settings.agent_client_ids else policy.EXTERNAL
    dept = policy.dept_from_groups(c.get("groups"))
    p = policy.Principal(org=c["owner"], user_name=c["name"], display_name=c.get("displayName") or c["name"],
                         dept=dept, channel=channel)
    p.pack = policy.resolve_pack(p.org, p.user_name, dept)
    return p


def _trace(ctx: Context) -> tuple[str, str]:
    h = {k.lower(): v for k, v in (ctx.headers or {}).items()}
    # 请求头只能是 ASCII，任务描述按 URL 编码传输
    return h.get("x-hub-trace-id") or h.get("mcp-session-id") or f"req-{ctx.request_id}", unquote(h.get("x-hub-task", ""))


def _audit(ctx: Context, p: policy.Principal, kind: str, tool: str, detail: str, result: str) -> None:
    trace_id, task = _trace(ctx)
    db.add_audit(trace_id=trace_id, org=p.org, user_name=p.user_name, display_name=p.display_name, dept=p.dept,
                 channel=p.channel, kind=kind, tool=tool, detail=detail, result=result, summary=task)


@mcp.tool(description="查看当前员工的身份、部门、岗位包，以及能用的技能和知识库")
def whoami(ctx: Context) -> str:
    p = _principal()
    _audit(ctx, p, "登录", "whoami", f"{p.channel}接入，身份：{p.display_name} / 岗位包「{p.pack['name']}」", "通过")
    return json.dumps({
        "name": p.display_name, "dept": p.dept, "channel": p.channel, "role_pack": p.pack["name"],
        "skills": p.pack["skills"] if not p.is_external else [],
        "knowledge_bases": [KB_REGISTRY[k]["name"] for k in policy.allowed_kbs(p)],
        "max_action_level": p.pack["max_action_level"],
    }, ensure_ascii=False)


@mcp.tool(description="列出当前岗位包内可用的技能（id、名称、说明）")
def list_skills(ctx: Context) -> str:
    p = _principal()
    if p.is_external or not policy.can_use_tool(p, "skill.read"):
        _audit(ctx, p, "拦截", "skill.read", "当前入口或岗位包不允许读取技能", "拒绝")
        return "无权读取技能。"
    allowed = set(p.pack["skills"])
    skills = [s for s in content.list_skills() if s["id"] in allowed]
    _audit(ctx, p, "技能", "skill.read", f"列出技能 {len(skills)} 个", "通过")
    return json.dumps([{k: s[k] for k in ("id", "name", "description")} for s in skills], ensure_ascii=False)


@mcp.tool(description="读取一个技能的完整内容（SKILL.md），按其中的步骤完成任务")
def read_skill(skill_id: str, ctx: Context) -> str:
    p = _principal()
    if p.is_external or skill_id not in p.pack["skills"] or not policy.can_use_tool(p, "skill.read"):
        _audit(ctx, p, "拦截", "skill.read", f"技能「{skill_id}」不在岗位包「{p.pack['name']}」内", "拒绝")
        return f"无权读取技能 {skill_id}。"
    text = content.read_skill(skill_id)
    if text is None:
        return f"技能 {skill_id} 不存在。"
    _audit(ctx, p, "技能", "skill.read", f"加载技能「{skill_id}」", "通过")
    return text


@mcp.tool(description="检索企业知识库。knowledge_base 可选，填知识库名称则只查该库；不填则查所有有权限的库")
def search_knowledge(query: str, ctx: Context, knowledge_base: str | None = None) -> str:
    p = _principal()
    if not policy.can_use_tool(p, "kb.search"):
        _audit(ctx, p, "拦截", "kb.search", f"岗位包「{p.pack['name']}」没有知识库检索工具", "拒绝")
        return "无权检索知识库。"
    allowed = policy.allowed_kbs(p)
    if knowledge_base:
        kb_id = KB_BY_NAME.get(knowledge_base) or (knowledge_base if knowledge_base in KB_REGISTRY else None)
        if kb_id is None:
            return f"知识库「{knowledge_base}」不存在。可用的知识库：{'、'.join(KB_REGISTRY[k]['name'] for k in allowed)}"
        if kb_id not in allowed:
            reason = policy.explain_kb_denial(p, kb_id)
            _audit(ctx, p, "拦截", "kb.search", f"「{query}」→ 目标知识库「{KB_REGISTRY[kb_id]['name']}」：{reason}", "拒绝")
            return f"无权检索「{KB_REGISTRY[kb_id]['name']}」：{reason}。该请求已记录。"
        targets = [kb_id]
    else:
        targets = allowed
    if not targets:
        _audit(ctx, p, "拦截", "kb.search", f"「{query}」→ 当前入口没有可检索的知识库", "拒绝")
        return "当前入口没有可检索的知识库。"
    hits = content.search(query, targets)
    found = "、".join(sorted({h["knowledge_base"] for h in hits})) or "无结果"
    _audit(ctx, p, "检索", "kb.search", f"「{query}」→ {found}（{len(hits)} 条）", "通过")
    if not hits:
        return "没有找到相关内容。"
    return json.dumps(hits, ensure_ascii=False)


COVER_WAIT_SECONDS = 90


@mcp.tool(description="生成小红书封面图：派发到公司 GPU 节点排队执行，一次出 3 版。"
                      "title 为封面主文案（8–12 字为宜），description 可补充画面风格。"
                      "90 秒内完成则直接返回图片链接，否则返回任务号，稍后用 get_cover_task 查询")
def generate_cover(title: str, ctx: Context, description: str | None = None) -> str:
    p = _principal()
    if p.is_external or not policy.can_use_tool(p, "image.cover"):
        _audit(ctx, p, "拦截", "image.cover", f"岗位包「{p.pack['name']}」没有生成封面图的权限", "拒绝")
        return "无权使用生成封面图。"
    trace_id, _ = _trace(ctx)
    prompt = f"小红书封面，主文案「{title}」，{description or '柔和自然光，干净留白，高级质感'}"
    t = gpu.submit_task(trace_id=trace_id, org=p.org, user_name=p.user_name, display_name=p.display_name, dept=p.dept,
                        channel=p.channel, workflow="xhs-cover", params={"prompt": prompt, "title": title})
    _audit(ctx, p, "工具", "image.cover", f"派发封面任务「{title}」，前面排队 {t['ahead']} 个", "通过")
    return json.dumps(gpu.describe(gpu.wait_task(t["id"], COVER_WAIT_SECONDS)), ensure_ascii=False)


@mcp.tool(description="查询封面图任务的进度和结果")
def get_cover_task(task_id: str, ctx: Context) -> str:
    p = _principal()
    t = db.gpu_task(task_id)
    if not t or t["org"] != p.org or t["user_name"] != p.user_name:
        return f"没有找到任务 {task_id}。"
    return json.dumps(gpu.describe(t), ensure_ascii=False)


db.init_schema()
app = mcp.streamable_http_app(host="0.0.0.0")
