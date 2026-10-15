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
from urllib.parse import unquote

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer

from . import content, db, policy
from .auth import _jwks_client
from .config import settings
from .content import KB_BY_NAME, KB_REGISTRY

INSTRUCTIONS = """这是企业智能体中枢。你可以：
- whoami：查看当前员工身份和岗位包
- list_skills / read_skill：读取岗位包内的技能（SKILL.md），按技能里的步骤完成工作
- search_knowledge：检索有权限的企业知识库
权限由中枢按员工岗位包强制执行，被拒绝时请如实告知员工，不要尝试绕过。"""


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


db.init_schema()
app = mcp.streamable_http_app(host="0.0.0.0")
