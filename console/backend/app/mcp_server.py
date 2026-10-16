"""中枢 MCP Server：员工的 agent（以及经授权的外部智能体）通过它使用技能和知识库。

运行：uv run uvicorn app.mcp_server:app --port 8200
地址：http://<中枢>:8200/mcp（Streamable HTTP），请求头带 Authorization: Bearer <Casdoor 令牌>

- 身份：令牌由 Casdoor 签发，按签发它的应用区分入口——官方 agent 应用 = 「官方 agent」，外部应用 = 「外部智能体」
- 权限：每次调用都按员工的岗位包判断（policy.py），提示词无法绕过
- 审计：每次调用写一条审计事件；同一 MCP 会话共用一个 trace_id（也可用请求头 X-Hub-Trace-Id 指定），
  请求头 X-Hub-Task 可以带上任务描述（URL 编码），显示在控制台审计日志里
"""

from __future__ import annotations

import base64
import binascii
import json
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer

from . import comfyui, content, db, gpu, policy
from .auth import _jwks_client
from .config import settings
from .content import KB_BY_NAME, KB_REGISTRY

INSTRUCTIONS = """这是企业智能体中枢。你可以：
- whoami：查看当前员工身份和岗位包
- list_skills / read_skill：读取岗位包内的技能（SKILL.md），按技能里的步骤完成工作
- search_knowledge：检索有权限的企业知识库
- generate_cover / generate_video / get_cover_task：派发到公司 GPU 节点生成封面图或短视频（排队执行）
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


def _dispatch(p: policy.Principal, ctx: Context, tool: str, workflow: str, params: dict, note: str) -> str:
    """派发一个 GPU 任务并等待结果：等待时长取工作流自己声明的值（生图 90 秒、视频 15 分钟）。"""
    spec = gpu.workflow_spec(workflow)
    trace_id, _ = _trace(ctx)
    t = gpu.submit_task(trace_id=trace_id, org=p.org, user_name=p.user_name, display_name=p.display_name,
                        dept=p.dept, channel=p.channel, workflow=workflow, params=params)
    _audit(ctx, p, "工具", tool, f"派发{spec['label']}任务{note}，前面排队 {t['ahead']} 个", "通过")
    return json.dumps(gpu.describe(gpu.wait_task(t["id"], spec["wait_seconds"])), ensure_ascii=False)


@mcp.tool(description="生成小红书封面图：派发到公司 GPU 节点排队执行。"
                      "title 为封面主文案（8–12 字为宜），description 可补充画面风格。"
                      "完成后返回图片链接；若还在排队/生成，返回任务号，稍后用 get_cover_task 查询")
def generate_cover(title: str, ctx: Context, description: str | None = None) -> str:
    p = _principal()
    if p.is_external or not policy.can_use_tool(p, "image.cover"):
        _audit(ctx, p, "拦截", "image.cover", f"岗位包「{p.pack['name']}」没有生成封面图的权限", "拒绝")
        return "无权使用生成封面图。"
    prompt = f"小红书封面，主文案「{title}」，{description or '柔和自然光，干净留白，高级质感'}"
    return _dispatch(p, ctx, "image.cover", "zimage-cover", {"prompt": prompt, "title": title}, f"「{title}」")


MAX_REF_BYTES = 12 * 1024 * 1024  # 参考图上限（百万像素级产品图够用）


def _reference_bytes(reference_image: str) -> bytes | None:
    """取参考图内容：优先 base64。

    员工的参考图在员工电脑上，中枢 MCP 读不到那个路径——正常走 base64
    （agent 读本地文件后编码传过来），本地测试时也可以直接给中枢能访问的路径。
    """
    data = reference_image.strip()
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    if len(data) > 256 and not data.startswith(("/", "~")):
        try:
            return base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error):
            pass
    path = Path(data).expanduser()
    return path.read_bytes() if path.is_file() else None


@mcp.tool(description="生成短视频：给一句画面描述，在公司 GPU 节点上生成 4–5 秒的竖版视频（含音频）。"
                      "给了参考图就是图生视频（画面跟着这张图走，适合产品图/人物图动起来）——"
                      "参考图请用 base64 传入（先读本机图片再编码），不要传本机文件路径，"
                      "不给就是文生视频。视频是分钟级任务，一般先返回任务号，"
                      "用 get_cover_task 查进度和视频链接。可选 seconds（默认 4，范围 1–9）控制时长")
def generate_video(prompt: str, ctx: Context, reference_image: str | None = None, seconds: float = 4.0) -> str:
    p = _principal()
    if p.is_external or not policy.can_use_tool(p, "video.clip"):
        _audit(ctx, p, "拦截", "video.clip", f"岗位包「{p.pack['name']}」没有生成短视频的权限", "拒绝")
        return "无权使用生成短视频。"

    remote = None
    workflow = "minimax-video-t2v"
    if reference_image:
        data = _reference_bytes(reference_image)
        if data is None:
            _audit(ctx, p, "拦截", "video.clip", "参考图无法读取（既不是 base64 也不是中枢可访问的文件）", "拒绝")
            return ("读不到参考图。图片在员工电脑上，中枢读不到本机路径——"
                    "请把图片内容按 base64 传入 reference_image。")
        if len(data) > MAX_REF_BYTES:
            _audit(ctx, p, "拦截", "video.clip", f"参考图过大（{len(data) // 1024}KB）", "拒绝")
            return f"参考图太大（{len(data) // 1024}KB），请压缩到 {MAX_REF_BYTES // (1024 * 1024)}MB 以内。"
        node = gpu.online_node()
        if node is None:
            _audit(ctx, p, "拦截", "video.clip", "当前没有在线的 GPU 节点", "拒绝")
            return "当前没有在线的 GPU 节点，稍后再试。"
        try:
            # 参考图先上传到节点的 ComfyUI input 目录，工作流里按文件名引用
            remote = comfyui.ComfyUI(node["url"]).upload_image(
                f"hub-{uuid.uuid4().hex[:8]}.png", data, subfolder="hub")
            workflow = "minimax-video"
        except Exception as e:  # noqa: BLE001 节点临时故障，如实告知
            _audit(ctx, p, "拦截", "video.clip", f"上传参考图到 {node['id']} 失败：{e}", "拒绝")
            return f"上传参考图失败：{e}"

    frames = comfyui.frames_for_seconds(seconds)
    timeline = comfyui.build_timeline(prompt, remote, frames, 768, 1344)
    params = {"prompt": prompt, "timeline_data": timeline, "title": prompt[:20],
              "seconds": round(frames / 24.0, 1)}
    if remote:
        params["reference_image"] = remote
    mode = "图生视频" if remote else "文生视频"
    return _dispatch(p, ctx, "video.clip", workflow, params, f"「{prompt[:20]}」（{mode}，约 {params['seconds']} 秒）")


@mcp.tool(description="查询出图/出视频任务的进度与结果（图片在 images，视频在 videos）")
def get_cover_task(task_id: str, ctx: Context) -> str:
    p = _principal()
    t = db.gpu_task(task_id)
    if not t or t["org"] != p.org or t["user_name"] != p.user_name:
        return f"没有找到任务 {task_id}。"
    return json.dumps(gpu.describe(t), ensure_ascii=False)


db.init_schema()
app = mcp.streamable_http_app(host="0.0.0.0")
