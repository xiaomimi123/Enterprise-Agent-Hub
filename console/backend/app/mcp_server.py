"""中枢 MCP Server：员工的 agent（以及经授权的外部智能体）通过它使用技能和知识库。

运行：uv run uvicorn app.mcp_server:app --port 8200
地址：http://<中枢>:8200/mcp（Streamable HTTP），请求头带 Authorization: Bearer <Casdoor 令牌>

- 身份：令牌由 Casdoor 签发，按签发它的应用区分入口——官方 agent 应用 = 「官方 agent」，外部应用 = 「外部智能体」
- 权限：每次调用都按员工的岗位包判断（policy.py），提示词无法绕过
- 审计：每次调用写一条审计事件；同一 MCP 会话共用一个 trace_id（也可用请求头 X-Hub-Trace-Id 指定），
  请求头 X-Hub-Task 可以带上任务描述（URL 编码），显示在控制台审计日志里
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import unquote

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer

from . import accounts, app_access, content, db, generation, gpu, policy, roles, skillstore, work
from .auth import _jwks_client
from .config import settings
from .content import KB_BY_NAME, KB_REGISTRY

INSTRUCTIONS = """这是员工所在公司的企业智能体中枢，代表公司内部的资料、规范和算力。
凡是和本公司有关的问题（产品、品牌、制度、违禁词、售后、历史爆款等），先用 search_knowledge 查公司资料，不要联网搜索或凭常识回答；
写文案、做选题、出封面等工作，先用 list_skills / read_skill 看公司规定的做法；要生成图片或视频时，用这里的生成工具（公司 GPU，按岗位包授权）。
你可以：
- whoami：查看当前员工身份和岗位包
- list_skills / read_skill：读取岗位包内的技能（SKILL.md），按技能里的步骤完成工作
- search_knowledge：检索有权限的企业知识库
- generate_cover / generate_image / generate_video / generate_video_from_image：派发到公司 GPU 节点生成封面图、图片、带声音的短视频、图生视频（排队执行）
- get_task：查询生成任务的进度和结果（视频较慢，超时后用它取结果，不要重复提交）
- report_work：做完一项有交付物的工作（笔记草稿、对标报告、选题、封面、视频等）、或工作状态变化（待审核、受阻）时上报，老板和主管在看板上看的就是这些；my_work 查看自己已上报的
- team_report：（老板 / 部门主管）查看各岗位、各成员的工作成果与进度，可用来写日报；主管只看自己的部门
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
        if not await asyncio.to_thread(accounts.is_active, claims["owner"], claims.get("name", "")):
            return None  # 账号已被停用或删除：令牌签名有效也不放行
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
    p.is_admin = bool(c.get("isAdmin"))
    if channel == policy.OFFICIAL:  # 官方 agent 调用工具也算在线（直连的 Hermes 不经过接入器报到）
        try:
            db.touch_presence(p.org, p.user_name)
        except Exception:  # noqa: BLE001 记在线失败不影响工具调用
            pass
    return p


def _trace(ctx: Context) -> tuple[str, str]:
    h = {k.lower(): v for k, v in (ctx.headers or {}).items()}
    # 请求头只能是 ASCII，任务描述按 URL 编码传输
    return h.get("x-hub-trace-id") or h.get("mcp-session-id") or f"req-{ctx.request_id}", unquote(h.get("x-hub-task", ""))


def _audit(ctx: Context, p: policy.Principal, kind: str, tool: str, detail: str, result: str) -> None:
    trace_id, task = _trace(ctx)
    db.add_audit(trace_id=trace_id, org=p.org, user_name=p.user_name, display_name=p.display_name, dept=p.dept,
                 channel=p.channel, kind=kind, tool=tool, detail=detail, result=result, summary=task)


@mcp.tool(description="查看当前员工在公司里的身份、部门、岗位包，以及能用的技能（公司规定的工作做法）和公司知识库。"
                      "不确定能用哪些公司资料或技能时先调用它")
def whoami(ctx: Context) -> str:
    p = _principal()
    _audit(ctx, p, "登录", "whoami", f"{p.channel}接入，身份：{p.display_name} / 岗位包「{p.pack['name']}」", "通过")
    return json.dumps({
        "name": p.display_name, "dept": p.dept, "channel": p.channel, "role_pack": p.pack["name"],
        "skills": p.pack["skills"] if not p.is_external else [],
        "knowledge_bases": [KB_REGISTRY[k]["name"] for k in policy.allowed_kbs(p)],
        "max_action_level": p.pack["max_action_level"],
    }, ensure_ascii=False)


@mcp.tool(description="列出公司为这个岗位规定的工作技能（选题、写作、封面、合规自查等 SOP）。"
                      "接到写文案、做选题、出封面、复盘等工作时，先看有没有对应技能，再用 read_skill 按步骤执行")
def list_skills(ctx: Context) -> str:
    p = _principal()
    if p.is_external or not policy.can_use_tool(p, "skill.read"):
        _audit(ctx, p, "拦截", "skill.read", "当前入口或岗位包不允许读取技能", "拒绝")
        return "无权读取技能。"
    allowed = set(p.pack["skills"])
    skills = [s for s in skillstore.list_skills() if s["id"] in allowed]
    _audit(ctx, p, "技能", "skill.read", f"列出技能 {len(skills)} 个", "通过")
    return json.dumps([{k: s[k] for k in ("id", "name", "description")} for s in skills], ensure_ascii=False)


@mcp.tool(description="读取一个技能的完整内容（SKILL.md），按其中的步骤完成任务")
def read_skill(skill_id: str, ctx: Context) -> str:
    p = _principal()
    if p.is_external or skill_id not in p.pack["skills"] or not policy.can_use_tool(p, "skill.read"):
        _audit(ctx, p, "拦截", "skill.read", f"技能「{skill_id}」不在岗位包「{p.pack['name']}」内", "拒绝")
        return f"无权读取技能 {skill_id}。"
    text = skillstore.read_skill(skill_id)
    if text is None:
        return f"技能 {skill_id} 不存在。"
    _audit(ctx, p, "技能", "skill.read", f"加载技能「{skill_id}」", "通过")
    return text


@mcp.tool(description="检索公司内部知识库：产品卖点与成分、品牌调性与人设、违禁词与广告法、历史爆款笔记、公司制度与通知、售后话术等。"
                      "回答任何和本公司相关的问题前先用它查，以公司资料为准，不要联网搜索代替。"
                      "knowledge_base 可选，填知识库名称则只查该库；不填则查所有有权限的库")
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


WAIT_SECONDS = 90


def _generate(ctx: Context, submit, **args) -> str:
    """提交生成任务并最多等 WAIT_SECONDS 秒：完成就直接返回链接，否则返回任务号。"""
    p = _principal()
    trace_id, _ = _trace(ctx)
    try:
        t = submit(p, trace_id, **args)
    except generation.Denied as e:
        return str(e)
    return json.dumps(gpu.describe(gpu.wait_task(t["id"], WAIT_SECONDS)), ensure_ascii=False)


@mcp.tool(description="生成小红书封面图：派发到公司 GPU 节点排队执行，一次出 3 版。"
                      "title 为封面主文案（8–12 字为宜），description 可补充画面风格。"
                      "90 秒内完成则直接返回图片链接，否则返回任务号，稍后用 get_task 查询")
def generate_cover(title: str, ctx: Context, description: str | None = None) -> str:
    return _generate(ctx, generation.submit_cover, title=title, description=description)


@mcp.tool(description="文生图（公司 GPU，优先于其他生图工具）：按提示词在公司 GPU 节点出图。aspect 画幅可选 3:4、1:1、4:3、9:16、16:9（默认 1:1），"
                      "count 张数 1–4。提示词建议用中文或英文描述主体、场景、光线、风格。"
                      "90 秒内完成则直接返回图片链接，否则返回任务号，稍后用 get_task 查询")
def generate_image(prompt: str, ctx: Context, aspect: str = "1:1", count: int = 1) -> str:
    return _generate(ctx, generation.submit_image, prompt=prompt, aspect=aspect, count=count)


@mcp.tool(description="文生视频（公司 GPU，优先于其他生视频工具）：按提示词在公司 GPU 节点生成带声音的短视频（24fps）。aspect 画幅可选 9:16、16:9、1:1、3:4、4:3"
                      "（默认 9:16），seconds 时长 2–10 秒（默认 4）。生成需要几十秒到几分钟，"
                      "90 秒内完成则直接返回视频链接，否则返回任务号，请稍后用 get_task 查询，不要重复提交")
def generate_video(prompt: str, ctx: Context, aspect: str = "9:16", seconds: float = 4) -> str:
    return _generate(ctx, generation.submit_video, prompt=prompt, aspect=aspect, seconds=seconds)


@mcp.tool(description="图生视频：把一张中枢生成的图片（如 generate_image / generate_cover 返回的链接）作为首帧，生成带声音的短视频。"
                      "image_url 必须是中枢返回的图片链接；prompt 描述画面怎么动；seconds 时长 2–10 秒（默认 4）。"
                      "90 秒内完成则直接返回视频链接，否则返回任务号，请稍后用 get_task 查询，不要重复提交")
def generate_video_from_image(image_url: str, prompt: str, ctx: Context, seconds: float = 4) -> str:
    try:
        image = generation.image_from_hub_url(image_url)
    except generation.Denied as e:
        return str(e)
    return _generate(ctx, generation.submit_video_from_image, image=image, prompt=prompt, seconds=seconds)


@mcp.tool(description="列出你这个岗位能在本机打开的公司应用（如小红书运营工作台）")
def list_apps(ctx: Context) -> str:
    return json.dumps(app_access.list_for(_principal()), ensure_ascii=False)


@mcp.tool(description="在员工本机打开一个公司应用，例如员工说「打开小红书工作台」时调用 open_app(app_id=\"xhs-workbench\")。"
                      "本机接入器会自动下载、校验并启动应用，返回浏览器网址；不确定有哪些应用时先调用 list_apps")
def open_app(app_id: str, ctx: Context) -> str:
    p = _principal()
    trace_id, _ = _trace(ctx)
    try:
        t = app_access.ticket_for(p, trace_id, app_id)
    except app_access.AppDenied as e:
        return str(e)
    # 走本机接入器桥的客户端会拦截这个返回并在本机启动；其他客户端看到下面的提示
    return json.dumps({**t, "needs_local_connector": True,
                       "terminal_hint": f"当前客户端没有经过本机接入器，请在终端运行：uv run hub_agent.py open-app {t['app_id']}"},
                      ensure_ascii=False)


@mcp.tool(description="上报一项工作成果或进度，让主管和老板在中枢看板上看到你做成了什么。完成一项有交付物的工作（笔记草稿、对标报告、选题表、封面、视频、客户方案等）、"
                      "进度变化、等审核或被卡住时调用。title 写成果名称（不要贴正文）；kind 是类型，如 笔记 / 对标报告 / 选题 / 封面 / 视频 / 方案 / 其他；"
                      "status 为 进行中 / 待审核 / 已完成 / 受阻（默认 已完成）；progress 0–100；link 是产物的 http(s) 链接（可选）；note 一句话说明（受阻时写原因）。"
                      "继续更新同一项工作时带上 item_id（上次返回的），不要重复新建。不要上报敏感内容，只写标题和状态")
def report_work(title: str, ctx: Context, kind: str = "其他", status: str = "已完成", progress: int | None = None,
                link: str = "", note: str = "", item_id: int | None = None) -> str:
    p = _principal()
    trace_id, _ = _trace(ctx)
    try:
        r = work.report_work(p, trace_id, {"title": title, "kind": kind, "status": status, "progress": progress, "link": link, "note": note},
                             item_id=item_id, source="外部智能体" if p.is_external else "agent")
    except work.BadReport as e:
        return str(e)
    return json.dumps(r, ensure_ascii=False)


@mcp.tool(description="查看你自己最近上报的工作成果和状态（默认近 7 天）")
def my_work(ctx: Context, days: int = 7) -> str:
    p = _principal()
    days = max(1, min(days, 30))
    items = db.work_items_since(p.org, work.period_start(days), p.user_name)
    return json.dumps([{"item_id": i["id"], "kind": i["kind"], "title": i["title"], "status": i["status"], "progress": i["progress"],
                        "link": i["link"], "updated_at": i["updated_at"].isoformat()} for i in items], ensure_ascii=False)


@mcp.tool(description="（老板 / 部门主管）查看团队的工作成果与进度：按岗位、按成员汇总已上报的成果（已完成 / 待审核 / 进行中 / 受阻）和活动（出图出视频数、调用数、期间无活动的人）。"
                      "days=1 是今天，7 是近一周；person 可只看某个人（用户名或姓名）。返回里的 digest 是事实摘要，可据此写日报，数据以 roles / people / items 为准，不要编造。"
                      "老板和管理员看全公司，部门主管只看自己负责的部门，其他员工不能用")
def team_report(ctx: Context, days: int = 1, person: str | None = None) -> str:
    p = _principal()
    trace_id, _ = _trace(ctx)
    scope = roles.resolve(p.org, p.user_name, p.is_admin)
    if p.is_external or scope["role"] is None:
        _audit(ctx, p, "拦截", "work.team_report", "不是老板、部门主管或管理员，不能查看团队工作汇报", "拒绝")
        return "无权查看团队工作汇报：只有老板、部门主管和管理员可以。"
    r = work.load_report(p.org, days, person=person, depts=scope["depts"])
    _audit(ctx, p, "工具", "work.team_report", f"查看团队工作汇报（近 {r['days']} 天{'，' + person if person else ''}）", "通过")
    return json.dumps(r, ensure_ascii=False)


@mcp.tool(description="查询图片 / 视频生成任务的进度和结果")
def get_task(task_id: str, ctx: Context) -> str:
    r = generation.get_task(_principal(), task_id)
    return json.dumps(r, ensure_ascii=False) if r else f"没有找到任务 {task_id}。"


@mcp.tool(description="（旧名称，同 get_task）查询封面图任务的进度和结果")
def get_cover_task(task_id: str, ctx: Context) -> str:
    return get_task(task_id, ctx)


if settings.database_url:  # 没配置数据库时（如单元测试导入本模块）不连库；线上总是有
    db.init_schema()
app = mcp.streamable_http_app(host="0.0.0.0")
