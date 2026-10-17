# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "pyyaml>=6"]
# ///
"""企业智能体中枢 · 员工端接入器。

在员工电脑上运行。它不改 Hermes 的代码，只负责：
1. 登录：浏览器打开中枢的登录页（生产环境为钉钉扫码），拿到员工本人的令牌
2. 领取配置：模型 key（按人计量）、中枢 MCP 地址、岗位包内的技能
3. 生成一套独立的 Hermes 配置（默认 ~/.hub-agent/hermes），与员工个人的 Hermes 配置完全隔开
4. 用这套配置启动 Hermes

用法：
    uv run agent/hub_agent.py login --hub http://<中枢>:8088          # 浏览器登录
    uv run agent/hub_agent.py login --hub ... --username u --password p  # 开发环境账号密码登录
    uv run agent/hub_agent.py chat                                     # 启动 Hermes（会先自动同步）
    uv run agent/hub_agent.py chat -q "帮我查一下保湿精华的卖点"          # 其余参数原样传给 hermes
    uv run agent/hub_agent.py sync | status | logout
    uv run agent/hub_agent.py mcp                                      # 本地 MCP 桥：给 WorkBuddy 等桌面智能体用

接 WorkBuddy、Cursor 等支持本地（stdio）MCP 的桌面智能体：在它的 mcp.json 里加一个服务器，
命令为 uv，参数为 ["run", "<路径>/agent/hub_agent.py", "mcp"]。桥会自动续期令牌，配置一次长期可用。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import shutil
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml

HOME = Path(os.environ.get("HUB_AGENT_HOME", Path.home() / ".hub-agent"))
CREDS = HOME / "credentials.json"
HERMES_HOME = HOME / "hermes"
SKILLS_DIR = HOME / "skills"
# WorkBuddy 的技能目录：中枢下发的技能放在 hub-<技能 id>/ 下，并带标记文件，只管理这些，不碰员工自己装的技能
WORKBUDDY_SKILLS = Path(os.environ.get("HUB_WORKBUDDY_SKILLS", Path.home() / ".workbuddy" / "skills"))
WB_PREFIX = "hub-"
WB_MARKER = ".hub-managed"
CALLBACK_PORT = 27891


_LOG = {"stream": None}


def log_to_stderr(on: bool = True) -> None:
    """MCP 桥模式下 stdout 只能输出协议消息，提示信息改写到 stderr。"""
    _LOG["stream"] = sys.stderr if on else None


def info(msg: str) -> None:
    print(f"\033[36m›\033[0m {msg}", file=_LOG["stream"] or sys.stdout)


def fail(msg: str) -> None:
    print(f"\033[31m✗\033[0m {msg}", file=sys.stderr)
    sys.exit(1)


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


# ---------------- 登录 ----------------

def load_creds() -> dict:
    if not CREDS.exists():
        fail("尚未登录，请先运行：hub_agent.py login --hub http://<中枢地址>:8088")
    return json.loads(CREDS.read_text(encoding="utf-8"))


def save_creds(hub: str, cfg: dict, tok: dict) -> dict:
    creds = {"hub": hub, "casdoor_url": cfg["casdoor_url"], "client_id": cfg["client_id"],
             "access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"),
             "expires_at": int(time.time()) + int(tok.get("expires_in") or 3600)}
    write_private(CREDS, json.dumps(creds, indent=2))
    return creds


def browser_login(hub: str, cfg: dict) -> dict:
    """授权码 + PKCE：本机起一个只接收一次回调的小服务，浏览器登录完成后自动拿到授权码。"""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h3>登录成功，可以关闭这个页面，回到终端。</h3>".encode())

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    url = f"{cfg['casdoor_url']}/login/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": cfg["client_id"], "response_type": "code", "redirect_uri": cfg["redirect_uri"],
        "scope": "openid profile", "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })
    info("正在打开浏览器登录；如果没有自动打开，请手动访问：")
    print(f"  {url}")
    webbrowser.open(url)
    deadline = time.time() + 300
    while "code" not in result and "error" not in result and time.time() < deadline:
        time.sleep(0.3)
    server.server_close()
    if result.get("state") != state or "code" not in result:
        fail(f"登录未完成：{result.get('error_description') or result.get('error') or '超时或状态不匹配'}")
    # 直接向 Casdoor 换令牌：公开客户端 + PKCE，本机不需要任何应用密钥
    r = httpx.post(f"{cfg['casdoor_url']}/api/login/oauth/access_token", timeout=20, data={
        "grant_type": "authorization_code", "client_id": cfg["client_id"], "code": result["code"],
        "code_verifier": verifier, "redirect_uri": cfg["redirect_uri"],
    }).json()
    if not r.get("access_token"):
        fail(f"登录失败：{r.get('error_description') or r.get('error')}")
    return r


def cmd_login(args) -> None:
    hub = args.hub.rstrip("/")
    r = httpx.get(f"{hub}/api/agent/config", timeout=10)
    if r.status_code != 200:
        fail(f"连不上中枢 {hub}：{r.text[:200]}")
    cfg = r.json()
    if args.username:
        if not cfg.get("password_login"):
            fail("中枢未开启账号密码登录，请去掉 --username 使用浏览器登录")
        r = httpx.post(f"{hub}/api/agent/token", json={"username": args.username, "password": args.password or ""},
                       timeout=20)
        if r.status_code != 200:
            fail(r.json().get("detail", r.text))
        tok = r.json()
    else:
        tok = browser_login(hub, cfg)
    save_creds(hub, cfg, tok)
    info("登录成功")
    cmd_sync(args)


def fresh_creds() -> dict:
    """令牌快过期时用 refresh_token 续期。"""
    creds = load_creds()
    if creds["expires_at"] - time.time() > 300:
        return creds
    if not creds.get("refresh_token"):
        fail("登录已过期，请重新运行 login")
    r = httpx.post(f"{creds['casdoor_url']}/api/login/oauth/refresh_token", timeout=20, data={
        "grant_type": "refresh_token", "client_id": creds["client_id"], "refresh_token": creds["refresh_token"],
        "scope": "openid profile",
    }).json()
    if not r.get("access_token"):
        fail("登录已过期，请重新运行 login")
    return save_creds(creds["hub"], creds, r)


# ---------------- 同步配置 ----------------

def new_trace_id() -> str:
    """一次工作会话（登录 → 检索 → 出图 → 模型调用）共用一个追踪 ID，中枢据此串起完整链路。"""
    return "tr-" + uuid.uuid4().hex[:12]


def task_from_args(hermes_args: list[str]) -> str:
    """从 chat 参数里取出员工的提问（-q / --query），作为任务描述显示在审计日志里。"""
    for i, a in enumerate(hermes_args):
        if a in ("-q", "--query") and i + 1 < len(hermes_args):
            return hermes_args[i + 1][:80]
    return ""


def cmd_sync(_args=None, trace_id: str | None = None, task: str = "") -> dict:
    creds = fresh_creds()
    trace_id = trace_id or new_trace_id()
    r = httpx.post(f"{creds['hub']}/api/agent/enroll", timeout=30, headers={
        "Authorization": f"Bearer {creds['access_token']}", "X-Hub-Trace-Id": trace_id, "X-Hub-Task": quote(task)})
    if r.status_code != 200:
        fail(f"领取配置失败：{r.json().get('detail', r.text)}")
    cfg = r.json()

    # 技能：先清空再写入，岗位包里撤掉的技能会随之消失
    if SKILLS_DIR.exists():
        shutil.rmtree(SKILLS_DIR)
    for s in cfg["skills"]:
        p = SKILLS_DIR / s["id"] / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(s["content"] or "", encoding="utf-8")

    # Hermes 配置：这个目录由接入器管理，每次同步整体重写
    env = {"HUB_AGENT_TOKEN": creds["access_token"]}
    conf: dict = {
        "mcp_servers": {"hub": {"url": cfg["mcp_url"], "headers": {
            "Authorization": "Bearer ${HUB_AGENT_TOKEN}", "X-Hub-Trace-Id": trace_id, "X-Hub-Task": quote(task)}}},
        "skills": {"external_dirs": [str(SKILLS_DIR)]},
        # 中枢工具是员工每天都要用的核心能力，直接交给模型，不走 Hermes 的延迟加载（tool_search）
        "tools": {"tool_search": {"enabled": "off"}},
    }
    if cfg.get("model"):
        m = cfg["model"]
        env["HUB_MODEL_KEY"] = m["api_key"]
        conf["model"] = {"provider": "custom", "default": m["model"], "base_url": m["base_url"],
                         "api_key": "${HUB_MODEL_KEY}"}
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    write_private(HERMES_HOME / "config.yaml", "# 由企业智能体中枢接入器生成，请勿手动修改\n"
                  + yaml.safe_dump(conf, allow_unicode=True, sort_keys=False))
    write_private(HERMES_HOME / ".env", "".join(f"{k}={v}\n" for k, v in env.items()))

    wb = sync_workbuddy_skills(cfg)
    if wb is not None:
        info(f"WorkBuddy：已同步岗位包技能 {wb} 个到 {WORKBUDDY_SKILLS}")
    e = cfg["employee"]
    info(f"{e['name']}（{e['role_pack']}）：已同步技能 {len(cfg['skills'])} 个"
         + (f"，模型 {cfg['model']['model']}" if cfg.get("model") else "，中枢未下发模型"))
    write_private(HOME / "profile.json", json.dumps(cfg | {"skills": [s["id"] for s in cfg["skills"]]},
                                                    ensure_ascii=False, indent=2))
    return cfg


def cmd_status(_args) -> None:
    creds = load_creds()
    left = int(creds["expires_at"] - time.time())
    prof = json.loads((HOME / "profile.json").read_text(encoding="utf-8")) if (HOME / "profile.json").exists() else {}
    e = prof.get("employee", {})
    print(f"中枢：{creds['hub']}")
    print(f"员工：{e.get('name', '?')} · 岗位包：{e.get('role_pack', '?')}")
    print(f"技能：{', '.join(prof.get('skills', [])) or '无'}")
    print(f"令牌：{'有效，剩余 %d 分钟' % (left // 60) if left > 0 else '已过期（下次 chat 会自动续期）'}")
    print(f"Hermes 配置目录：{HERMES_HOME}")


def cmd_logout(_args) -> None:
    for p in (CREDS, HERMES_HOME / ".env", HOME / "profile.json"):
        p.unlink(missing_ok=True)
    if SKILLS_DIR.exists():
        shutil.rmtree(SKILLS_DIR)
    info("已退出并清除本机的令牌、模型 key 和技能")


def cmd_chat(args) -> None:
    cmd_sync(trace_id=new_trace_id(), task=task_from_args(args.hermes_args))
    hermes = shutil.which("hermes")
    if not hermes:
        fail("没有找到 hermes 命令，请先安装 Hermes Agent")
    os.execvpe(hermes, [hermes, "chat", *args.hermes_args], {**os.environ, "HERMES_HOME": str(HERMES_HOME)})


# ---------------- WorkBuddy 技能同步 ----------------

GUIDE = """---
name: 企业中枢
description: 公司的企业智能体中枢（MCP 服务器 enterprise-hub）。凡是和本公司有关的问题——产品卖点与成分、品牌调性与人设、违禁词与广告法、历史爆款笔记、公司制度、售后话术——都先用 enterprise-hub 的 search_knowledge 查公司资料，不要联网搜索代替；写小红书笔记、做选题、出封面、合规自查、复盘等工作，按公司下发的 hub-* 技能步骤执行；要生成图片、封面、视频时用 enterprise-hub 的生成工具（公司 GPU）。
---

# 企业中枢使用说明

当前员工：{name}（岗位包「{pack}」）。权限由中枢按岗位包执行，被拒绝时如实告诉员工，不要尝试绕过。

| 要做的事 | 调用 enterprise-hub 的工具 |
|---|---|
| 查公司资料（产品、品牌、违禁词、制度、售后……） | `search_knowledge`（可指定 knowledge_base） |
| 看自己能用哪些资料和技能 | `whoami` |
| 按公司规定的步骤干活 | `list_skills` / `read_skill`（本机 hub-* 技能就是它们的副本） |
| 出小红书封面（一次 3 版） | `generate_cover` |
| 文生图 | `generate_image` |
| 文生视频 / 图生视频 | `generate_video` / `generate_video_from_image`（图片链接必须是中枢返回的） |
| 生成没在 90 秒内完成 | `get_task` 查进度，不要重复提交 |

技能里写的工具代号对应关系：`kb.search` → `search_knowledge`，`skill.read` → `read_skill`，`image.cover` → `generate_cover`，`image.generate` → `generate_image`，`video.generate` → `generate_video`。
"""


def _with_banner(content: str, pack: str) -> str:
    """在 frontmatter 之后加一行来源说明（frontmatter 必须留在最前面，WorkBuddy 才能识别技能）。"""
    banner = (f"> 由企业智能体中枢下发（岗位包「{pack}」），本机修改会在下次同步时被覆盖。"
              "需要的公司资料和生成能力通过 MCP 服务器 enterprise-hub 调用，见技能「企业中枢」。\n\n")
    if content.startswith("---\n") and (end := content.find("\n---", 4)) != -1:
        cut = content.find("\n", end + 4) + 1 or len(content)
        return content[:cut] + "\n" + banner + content[cut:].lstrip("\n")
    return banner + content


def sync_workbuddy_skills(cfg: dict, root: Path | None = None) -> int | None:
    """把岗位包技能同步到 WorkBuddy：新增的写入、撤掉的删除。没装 WorkBuddy 时返回 None。"""
    root = root or WORKBUDDY_SKILLS
    if not root.parent.exists():
        return None
    root.mkdir(exist_ok=True)
    e = cfg["employee"]
    wanted = {f"{WB_PREFIX}{s['id']}": _with_banner(s["content"] or "", e["role_pack"]) for s in cfg["skills"]}
    wanted[f"{WB_PREFIX}guide"] = GUIDE.format(name=e["name"], pack=e["role_pack"])
    for d in root.iterdir():
        if d.is_dir() and d.name.startswith(WB_PREFIX) and (d / WB_MARKER).exists() and d.name not in wanted:
            shutil.rmtree(d)
    for name, text in wanted.items():
        (root / name).mkdir(exist_ok=True)
        (root / name / "SKILL.md").write_text(text, encoding="utf-8")
        (root / name / WB_MARKER).write_text("由企业智能体中枢接入器管理，会被自动更新或删除\n", encoding="utf-8")
    return len(cfg["skills"])


# ---------------- 本地 MCP 桥 ----------------

def _post_mcp(http: httpx.Client, url: str, msg: dict, headers: dict) -> httpx.Response:
    creds = fresh_creds()  # 令牌快过期时自动续期
    return http.post(url, json=msg, headers={**headers, "Authorization": f"Bearer {creds['access_token']}"})


def _relay(resp: httpx.Response, out) -> None:
    """把中枢的回复写给桌面智能体：JSON 直接转发，SSE 流按事件拆出 data 逐条转发。"""
    if resp.status_code == 202 or not resp.content:
        return
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        data: list[str] = []
        for line in resp.text.splitlines() + [""]:
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line and data:
                out.write(("".join(data) + "\n").encode("utf-8"))
                data = []
    else:
        out.write(resp.content.rstrip(b"\n") + b"\n")
    out.flush()


def cmd_mcp(_args=None) -> None:
    """stdio ↔ 中枢 MCP（Streamable HTTP）的桥。stdout 只输出协议消息，日志写 stderr。"""
    log_to_stderr()
    try:  # 每次桌面智能体启动时拉一次最新的岗位包技能
        cmd_sync()
    except (Exception, SystemExit) as e:  # noqa: BLE001 同步失败不影响桥本身
        print(f"hub-agent mcp: 同步技能失败：{e}", file=sys.stderr, flush=True)
    creds = fresh_creds()
    mcp_url = httpx.get(f"{creds['hub']}/api/agent/config", timeout=15).json()["mcp_url"]
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "X-Hub-Trace-Id": new_trace_id(), "X-Hub-Task": quote("桌面智能体会话")}
    out = sys.stdout.buffer
    with httpx.Client(timeout=httpx.Timeout(30, read=300)) as http:
        for raw in sys.stdin.buffer:
            if not raw.strip():
                continue
            msg = json.loads(raw)
            try:
                resp = _post_mcp(http, mcp_url, msg, headers)
                if resp.status_code == 404 and "Mcp-Session-Id" in headers:  # 中枢重启后会话失效：去掉会话号重试
                    headers.pop("Mcp-Session-Id")
                    resp = _post_mcp(http, mcp_url, msg, headers)
                if sid := resp.headers.get("mcp-session-id"):
                    headers["Mcp-Session-Id"] = sid
                if resp.status_code >= 400 and resp.status_code != 202:
                    raise RuntimeError(f"中枢返回 HTTP {resp.status_code}：{resp.text[:200]}")
                _relay(resp, out)
            except Exception as e:  # noqa: BLE001 出错时给请求方一个 JSON-RPC 错误，而不是让桥退出
                print(f"hub-agent mcp: {e}", file=sys.stderr, flush=True)
                if "id" in msg:
                    err = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": f"中枢不可用：{e}"}}
                    out.write((json.dumps(err, ensure_ascii=False) + "\n").encode("utf-8"))
                    out.flush()


def main() -> None:
    # Windows 老控制台是 GBK：打印不了的符号替换掉，不让程序因为一个提示符崩溃
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description="企业智能体中枢 · 员工端接入器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("login", help="登录中枢")
    p.add_argument("--hub", required=True, help="中枢控制台地址，如 http://192.168.1.10:8088")
    p.add_argument("--username", help="开发环境：账号密码登录")
    p.add_argument("--password")
    sub.add_parser("sync", help="重新领取配置和技能")
    sub.add_parser("status", help="查看当前登录状态")
    sub.add_parser("logout", help="退出并清除本机凭证")
    sub.add_parser("chat", help="启动 Hermes（其余参数原样传给 hermes）")
    sub.add_parser("mcp", help="本地 MCP 桥（stdio），给 WorkBuddy 等桌面智能体用")
    # chat 后面的参数（如 -q、--resume）全部原样交给 hermes，不经过本程序解析
    if len(sys.argv) > 1 and sys.argv[1] == "chat":
        return cmd_chat(argparse.Namespace(hermes_args=sys.argv[2:]))
    args = ap.parse_args()
    {"login": cmd_login, "sync": cmd_sync, "status": cmd_status, "logout": cmd_logout, "chat": cmd_chat,
     "mcp": cmd_mcp}[args.cmd](args)


if __name__ == "__main__":
    main()
