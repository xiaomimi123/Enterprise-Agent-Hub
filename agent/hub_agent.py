# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "pyyaml>=6"]
# ///
"""企业智能体中枢 · 员工端接入器。

在员工电脑上运行。它不改 Hermes 的代码，只负责：
1. 登录：浏览器打开中枢的登录页（Casdoor 账号，首次登录先改初始密码），拿到员工本人的令牌
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
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import zipfile
import webbrowser
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml

VERSION = "0.4.0"
HOME = Path(os.environ.get("HUB_AGENT_HOME", Path.home() / ".hub-agent"))
CREDS = HOME / "credentials.json"
HERMES_HOME = HOME / "hermes"
SKILLS_DIR = HOME / "skills"
# WorkBuddy 的技能目录：中枢下发的技能放在 hub-<技能 id>/ 下，并带标记文件，只管理这些，不碰员工自己装的技能
WORKBUDDY_SKILLS = Path(os.environ.get("HUB_WORKBUDDY_SKILLS", Path.home() / ".workbuddy" / "skills"))
# CodeBuddy CLI：中枢下发的模型写进它的 models.json，名字带这个前缀作为标记，只管理带标记的条目，不碰员工自己加的模型
CODEBUDDY_HOME = Path(os.environ.get("HUB_CODEBUDDY_HOME", Path.home() / ".codebuddy"))
CB_MODEL_PREFIX = "公司中枢 · "
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


def cmd_sync(_args=None, trace_id: str | None = None, task: str = "", session_key: bool = False) -> dict:
    creds = fresh_creds()
    trace_id = trace_id or new_trace_id()
    headers = {"Authorization": f"Bearer {creds['access_token']}", "X-Hub-Trace-Id": trace_id, "X-Hub-Task": quote(task)}
    if session_key:  # Hermes 会话：向中枢要一把名字带追踪 ID 的会话专属 key，模型调用精确归属到这次会话
        headers["X-Hub-Key-Scope"] = "session"
    r = httpx.post(f"{creds['hub']}/api/agent/enroll", timeout=30, headers=headers)
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

    cb = sync_codebuddy_models(cfg)
    if cb:
        info(f"CodeBuddy CLI：{cb}")
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
    cmd_sync(trace_id=new_trace_id(), task=task_from_args(args.hermes_args), session_key=True)
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
| 员工说「打开小红书工作台」等打开公司工具 | `open_app`（先 `list_apps` 看能打开哪些；工具会在本机启动并返回网址，把网址告诉员工） |
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


def _read_json_file(f: Path) -> dict | None:
    """读 JSON 配置：不存在返回 {}，格式有误返回 None（调用方据此跳过，绝不覆盖员工的文件）。Windows 工具常带 BOM。"""
    try:
        raw = f.read_text(encoding="utf-8-sig") if f.exists() else ""
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _backup(f: Path) -> None:
    if f.exists():
        shutil.copy2(f, f.with_name(f"{f.name}.bak-hub-{time.strftime('%Y%m%d-%H%M%S')}"))


def sync_codebuddy_models(cfg: dict, home: Path | None = None, state_file: Path | None = None) -> str | None:
    """把中枢下发的模型写进 CodeBuddy CLI：models.json 加入带「公司中枢 · 」前缀的条目（OpenAI 接口格式，url 要写完整的
    /chat/completions 路径），并在员工没有自己选过模型时把它设为默认。没装 CodeBuddy 返回 None；岗位包不下发模型时清掉旧条目。
    密钥是员工本人的模型 key（按岗位包限定模型和额度），文件权限 600。"""
    home = home or CODEBUDDY_HOME
    state_file = state_file or HOME / "codebuddy-state.json"
    if not home.is_dir():
        return None
    models_f, settings_f = home / "models.json", home / "settings.json"
    models_doc, settings_doc = _read_json_file(models_f), _read_json_file(settings_f)
    if models_doc is None or settings_doc is None:
        return f"{models_f if models_doc is None else settings_f} 格式有误，已跳过，请手动检查"
    prev = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}
    m = cfg.get("model")
    ids = list(dict.fromkeys(m.get("models") or [m["model"]])) if m else []
    mine = [{"id": i, "name": f"{CB_MODEL_PREFIX}{i}", "vendor": "OpenAI", "apiKey": m["api_key"],
             "url": m["base_url"].rstrip("/") + "/chat/completions", "supportsToolCall": True} for i in ids]
    kept = [x for x in models_doc.get("models", []) if not str(x.get("name", "")).startswith(CB_MODEL_PREFIX) and x.get("id") not in ids]
    new_models = {**models_doc, "models": kept + mine}
    if not mine and not models_doc.get("models") and "models" not in models_doc:
        new_models = models_doc
    changed = new_models != models_doc
    if changed:
        _backup(models_f)
        write_private(models_f, json.dumps(new_models, ensure_ascii=False, indent=2) + "\n")
    # settings.json：① 默认模型——员工没设过、或还是上次中枢设的那个，才改成中枢的默认模型，不覆盖员工自己的选择；
    # ② 放行 DeferExecuteTool——CodeBuddy 把 MCP 工具当延迟加载工具，经它调用；无人值守（-p，如工作台的 CLI 模式）时没有权限弹窗，
    # 不放行中枢工具就会被拒绝。它对所有延迟加载的 MCP 工具生效，中枢工具本身仍由岗位包按人限制。
    new_settings = dict(settings_doc)
    current = new_settings.get("model")
    note = ""
    if m and (not current or current == prev.get("default")) and current != m["model"]:
        new_settings["model"] = m["model"]
        note = f"，默认模型 {m['model']}"
    elif not m and current and current == prev.get("default"):
        new_settings.pop("model", None)
    perms = dict(new_settings.get("permissions") or {})
    allow = list(perms.get("allow") or [])
    if "DeferExecuteTool" not in allow:
        perms["allow"] = allow + ["DeferExecuteTool"]
        new_settings["permissions"] = perms
        note += "，已放行中枢工具的无人值守调用"
    if new_settings != settings_doc:
        _backup(settings_f)
        write_private(settings_f, json.dumps(new_settings, ensure_ascii=False, indent=2) + "\n")
    write_private(state_file, json.dumps({"default": m["model"] if m else None}, ensure_ascii=False))
    return f"已同步中枢模型 {len(mine)} 个到 {models_f}{note}" if m else f"中枢未下发模型（岗位包用自带模型），已清理中枢写入的条目{note}"


def codebuddy_mcp_file(home: Path) -> Path:
    """CodeBuddy CLI 读取 MCP 配置的文件：按它的优先级取第一个已存在的（同一层级内不合并），都没有就新建推荐的 .mcp.json。
    只有旧的 ~/.codebuddy.json 里已经有 MCP 服务器时才写它，避免新建 .mcp.json 把员工原有的服务器顶掉。"""
    for name in (".mcp.json", "mcp.json"):
        if (home / name).exists():
            return home / name
    legacy = home.parent / ".codebuddy.json"
    data = _read_json_file(legacy) if legacy.exists() else {}
    if data and data.get("mcpServers"):
        return legacy
    return home / ".mcp.json"


# ---------------- 一键接入：自动配置桌面 agent ----------------

MCP_SERVER_NAME = "enterprise-hub"


def agent_clients() -> list[dict]:
    """支持自动配置的桌面 agent：detect 目录存在才算装了，config 是它的 MCP 配置文件。"""
    home = Path.home()
    if sys.platform == "win32":
        claude = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Claude"
    elif sys.platform == "darwin":
        claude = home / "Library" / "Application Support" / "Claude"
    else:
        claude = home / ".config" / "Claude"
    cb = CODEBUDDY_HOME
    if shutil.which("codebuddy") and not cb.exists():
        cb.mkdir(parents=True, exist_ok=True)  # 装了命令行但还没运行过，目录还不存在
    return [
        {"name": "WorkBuddy", "detect": home / ".workbuddy", "config": home / ".workbuddy" / "mcp.json"},
        {"name": "CodeBuddy CLI", "detect": cb, "config": codebuddy_mcp_file(cb)},
        {"name": "Cursor", "detect": home / ".cursor", "config": home / ".cursor" / "mcp.json"},
        {"name": "Claude 桌面版", "detect": claude, "config": claude / "claude_desktop_config.json"},
    ]


def configure_agents(clients: list[dict], command: str, script: str) -> list[tuple[str, str]]:
    """把中枢写进每个已安装 agent 的 MCP 配置：保留原有内容，改之前备份，已是最新则不动，格式坏了不覆盖。"""
    out = []
    for c in clients:
        entry = {"command": command, "args": ["run", script, "mcp", "--client", c["name"]],
                 "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}}
        if not c["detect"].is_dir():
            out.append((c["name"], "未安装"))
            continue
        f: Path = c["config"]
        try:
            raw = f.read_text(encoding="utf-8-sig") if f.exists() else ""  # Windows 工具常带 BOM
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:
            out.append((c["name"], f"配置文件格式有误，已跳过，请手动检查 {f}"))
            continue
        servers = data.setdefault("mcpServers", {})
        if servers.get(MCP_SERVER_NAME) == entry:
            out.append((c["name"], "已是最新"))
            continue
        if f.exists():
            shutil.copy2(f, f.with_name(f"{f.name}.bak-hub-{time.strftime('%Y%m%d-%H%M%S')}"))
        servers[MCP_SERVER_NAME] = entry
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out.append((c["name"], "已配置"))
    return out


def find_uv() -> str:
    """配置里写 uv 的完整路径：桌面 agent 启动子进程时不一定带着用户的 PATH。"""
    found = shutil.which("uv")
    if found:
        return found
    exe = Path.home() / ".local" / "bin" / ("uv.exe" if sys.platform == "win32" else "uv")
    return str(exe) if exe.exists() else "uv"


def cmd_setup(args) -> None:
    """一键接入：没登录（或换了中枢）就浏览器登录，然后同步，再自动配置本机装的桌面 agent。"""
    hub = args.hub.rstrip("/")
    clients = agent_clients()  # 先探测：装了 CodeBuddy 命令行会在这里建好目录，下面的同步才会写入中枢模型
    creds = json.loads(CREDS.read_text(encoding="utf-8")) if CREDS.exists() else {}
    if creds.get("hub") != hub or not creds.get("refresh_token"):
        cmd_login(argparse.Namespace(hub=hub, username=None, password=None))
    else:
        try:
            cmd_sync()
        except SystemExit:  # 续期令牌过期：重新登录
            cmd_login(argparse.Namespace(hub=hub, username=None, password=None))
    results = configure_agents(clients, find_uv(), str(Path(__file__).resolve()))
    print()
    for name, status in results:
        info(f"{name}：{status}")
    if not shutil.which("codebuddy"):
        info("提示：要在小红书工作台里用浏览器自动化，需要先安装 CodeBuddy CLI（需要 Node.js）：npm install -g @tencent-ai/codebuddy-code ，装好后重新运行这条命令。只用 WorkBuddy 的话可以不装。")
    done = [n for n, s in results if s in ("已配置", "已是最新")]
    if done:
        info(f"接入完成。请完全退出并重新打开 {'、'.join(done)}，在里面就能直接使用公司知识库、技能和出图出视频。")
    else:
        info("没有检测到 WorkBuddy、CodeBuddy CLI、Cursor 或 Claude 桌面版。装好后重新运行这条命令即可；也可以用 chat 子命令启动 Hermes。")


# ---------------- 应用：在员工本机打开中枢发布的应用 ----------------

APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
APP_MAX_BYTES = 50 * 1024 * 1024
APP_MAX_FILES = 2000


def app_dir(app_id: str, version: str) -> Path:
    """应用包的本机目录。id 与版本都来自网络，只允许安全字符，绝不拼出目录之外的路径。"""
    if not APP_ID_RE.match(app_id or "") or not re.match(r"^[0-9A-Za-z][0-9A-Za-z._-]*$", version or "") or ".." in version:
        raise ValueError(f"应用 id 或版本不合法：{app_id!r} {version!r}")
    return HOME / "apps" / app_id / version


def prune_versions(app_id: str, keep: int = 2) -> None:
    """只保留最近使用的 keep 个版本目录，其余删除（员工数据在包外，不受影响）。"""
    root = HOME / "apps" / app_id
    if not root.is_dir():
        return
    versions = sorted((d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in versions[keep:]:
        shutil.rmtree(d, ignore_errors=True)


def _install_hint() -> str:
    if sys.platform == "darwin":
        return "macOS：已装 Homebrew 的话运行 brew install node；否则到 https://nodejs.org 下载 LTS 安装包（.pkg）。安装需要输入电脑密码。"
    if sys.platform == "win32":
        return "Windows：运行 winget install OpenJS.NodeJS.LTS，或到 https://nodejs.org 下载 LTS 安装包（.msi）；装完请重新打开 agent。"
    return "请用系统包管理器安装 Node.js 18 或更高版本（或使用 nvm）。"


def node_status(requires: dict, run=subprocess.run) -> tuple[bool, str]:
    """检查本机 Node 是否满足应用要求。满足返回 (True, 版本)；不满足返回 (False, 带安装指引的说明)。不自动安装。"""
    want = str((requires or {}).get("node") or "")
    if not want:
        return True, ""
    need = int(m.group(1)) if (m := re.search(r"(\d+)", want)) else 0
    try:
        r = run(["node", "-v"], capture_output=True, text=True, timeout=10)
        found = (m.group(1), r.stdout.strip()) if r.returncode == 0 and (m := re.match(r"v?(\d+)(?:\.\d+)*$", r.stdout.strip())) else None
    except (OSError, subprocess.SubprocessError):
        found = None
    if found and int(found[0]) >= need:
        return True, found[1]
    now = f"（当前 {found[1]}）" if found else "（本机没有检测到 Node.js）"
    return False, f"这个应用需要 Node.js {need} 或更高版本{now}。{_install_hint()}装好后再说一次「打开工作台」即可。"


def safe_extract(zip_path: Path, dest: Path, max_bytes: int = APP_MAX_BYTES, max_files: int = APP_MAX_FILES) -> None:
    """安全解压：拒绝绝对路径、.. 路径、符号链接、超大 / 超多文件（zip slip 与解压炸弹）。
    先解到 dest.partial，全部通过后再原子改名；任何一步失败都不留下目标目录或半成品。"""
    partial = dest.with_name(dest.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            infos = z.infolist()
            if len(infos) > max_files:
                raise ValueError(f"应用包文件数超过上限（{max_files}）")
            for i in infos:
                name = i.filename.replace("\\", "/")
                if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/"):
                    raise ValueError(f"应用包含不安全的路径：{i.filename}")
                if (i.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError(f"应用包含符号链接：{i.filename}")
            if sum(i.file_size for i in infos) > max_bytes:
                raise ValueError(f"应用包解压后大小超过上限（{max_bytes // 1024 // 1024}MB）")
            partial.mkdir(parents=True)
            written = 0
            for i in infos:
                target = partial / i.filename
                if i.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(i) as src, open(target, "wb") as out:
                    while chunk := src.read(1 << 16):
                        written += len(chunk)
                        if written > max_bytes:  # zip 头里的大小可以造假，按实际写出的字节再限一次
                            raise ValueError(f"应用包解压后大小超过上限（{max_bytes // 1024 // 1024}MB）")
                        out.write(chunk)
        partial.rename(dest)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def fetch_verified(url: str, sha256: str, dest: Path, client: httpx.Client) -> Path:
    """下载到临时文件，SHA-256 与中枢给的一致才改名到 dest；不一致立即删除。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    try:
        with client.stream("GET", url, timeout=120) as r:
            if r.status_code != 200:
                raise ValueError(f"下载失败：HTTP {r.status_code}（链接可能已过期，请重试）")
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    h.update(chunk)
                    f.write(chunk)
        if h.hexdigest() != sha256:
            raise ValueError("校验失败：应用包的 SHA-256 与中枢发布的不一致，已丢弃，没有执行")
        tmp.replace(dest)
        return dest
    except httpx.HTTPError as e:
        raise ValueError(f"下载失败：{e}") from e
    finally:
        tmp.unlink(missing_ok=True)


_APP_LOCKS: dict[str, threading.Lock] = {}
_APP_LOCKS_GUARD = threading.Lock()
LAUNCH_TIMEOUT = 90
# 工作台启动脚本的输出约定：已启动 / 已在运行 + 一行 URL:（见 apps/README.md）
_STARTED, _ALREADY = "已启动", "已在运行"


def parse_url(output: str) -> str | None:
    m = re.search(r"URL:\s*(\S+)", output or "")
    return m.group(1) if m else None


def _app_lock(app_id: str):
    """同一个应用的并发打开串行化：线程锁 + 文件锁（跨进程，如两个 agent 同时说「打开工作台」）。"""
    with _APP_LOCKS_GUARD:
        thread_lock = _APP_LOCKS.setdefault(app_id, threading.Lock())

    class _Lock:
        def __enter__(self):
            thread_lock.acquire()
            lock_dir = HOME / "apps" / app_id
            lock_dir.mkdir(parents=True, exist_ok=True)
            self.f = open(lock_dir / ".lock", "a+")
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.f, fcntl.LOCK_EX)
            except OSError:
                pass  # 拿不到文件锁时退化为只有线程锁，不阻止打开
            return self

        def __exit__(self, *exc):
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.f.close()
            thread_lock.release()
    return _Lock()


def _write_hub_mcp_config() -> Path:
    """给工作台里的底层 agent 用的 MCP 配置：同一个桥，嵌套模式（不重复同步技能 / 心跳 / enroll）。"""
    cfg = {"mcpServers": {MCP_SERVER_NAME: {
        "command": find_uv(), "args": ["run", str(Path(__file__).resolve()), "mcp", "--client", "工作台", "--nested"],
        "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}}}}
    f = HOME / "hub-mcp.json"
    write_private(f, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    return f


# ---------------- 应用能力预检：打开应用前检查它声明的依赖，缺什么说明并询问安装，只让对应功能不可用，不拦打开 ----------------
# app.json 的 requires：agent_cli（应用背后的命令行 agent，如 codebuddy）、capabilities（如 browser）、playwright_mcp（可选版本）。
# 预检是被动检查（不下载、不安装）；安装只在员工同意后做：交互终端里逐项询问，或由 agent 问过员工后运行 app-doctor --yes。
# 结果写进 ~/.hub-agent/capabilities/<应用 id>.json，并通过环境变量 HUB_CAPABILITIES_FILE 交给应用；应用每次用到时重新读取，
# 所以装好之后不用重启应用。文件里没有任何密钥。

CAPABILITIES_DIR = HOME / "capabilities"
CLI_PACKAGES = {"codebuddy": "@tencent-ai/codebuddy-code"}
CLI_LABELS = {"codebuddy": "CodeBuddy CLI"}
CLI_MIN_BROWSER_FIXES = "安装 Microsoft Edge（https://www.microsoft.com/edge）或 Google Chrome"


def find_system_browser(platform: str | None = None, exists=os.path.exists, which=shutil.which, env=None) -> str | None:
    """系统里的 Edge / Chrome（Playwright 优先用真实浏览器）。找到返回路径，没有返回 None。"""
    platform, env = platform or sys.platform, env if env is not None else os.environ
    if platform == "win32":
        roots = [env.get(k) for k in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA") if env.get(k)]
        rels = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"]
        cands = [os.path.join(r, rel) for r in roots for rel in rels]
    elif platform == "darwin":
        cands = ["/Applications/Microsoft Edge.app", "/Applications/Google Chrome.app"]
    else:
        return next((w for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge") if (w := which(n))), None)
    return next((c for c in cands if exists(c)), None)


def playwright_cached(version: str | None = None, home: Path | None = None, env=None) -> bool:
    """npx 的缓存里是否已有 @playwright/mcp（有就不用首次下载，第一次任务不会卡在「仍在连接中」）。"""
    env, home = env if env is not None else os.environ, home or Path.home()
    roots = [Path(env["LOCALAPPDATA"]) / "npm-cache" / "_npx"] if sys.platform == "win32" and env.get("LOCALAPPDATA") else []
    roots.append(home / ".npm" / "_npx")
    for root in roots:
        for pkg in root.glob("*/node_modules/@playwright/mcp/package.json") if root.is_dir() else []:
            try:
                if not version or json.loads(pkg.read_text(encoding="utf-8")).get("version") == version:
                    return True
            except (OSError, ValueError):
                continue
    return False


def _cli_install_fix(cli: str, which) -> dict:
    pkg = CLI_PACKAGES[cli]
    if not which("npm"):
        return {"text": f"先安装 Node.js，再执行：npm install -g {pkg}", "argv": None}
    argv = ["npm", "install", "-g", pkg] if sys.platform == "win32" else ["npm", "install", "-g", "--prefix", str(Path.home() / ".local"), pkg]
    return {"text": " ".join(argv), "argv": argv}


def preflight(requires: dict, *, which=None, browser_finder=None, cached=None,
              codebuddy_home: Path | None = None, profile: dict | None = None) -> dict:
    """被动检查应用声明的依赖。返回 {checks, capabilities, missing}：
    checks 每项 {id, label, ok, warn, detail, fix}；capabilities 里每个能力 {ready, missing, fixes}；missing 是没通过的检查名。"""
    requires = requires or {}
    which, browser_finder, cached = which or shutil.which, browser_finder or find_system_browser, cached or playwright_cached  # 调用时再取，便于测试替换
    cli = requires.get("agent_cli")
    wants_browser = "browser" in (requires.get("capabilities") or [])
    home = codebuddy_home or CODEBUDDY_HOME
    if profile is None:
        try:
            profile = json.loads((HOME / "profile.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            profile = {}
    checks: list[dict] = []

    def add(cid, label, ok, detail, fix=None, warn=False):
        checks.append({"id": cid, "label": label, "ok": bool(ok), "warn": bool(warn), "detail": detail, "fix": fix})

    if cli:
        label = CLI_LABELS.get(cli, cli)
        found = which(cli)
        add("agent_cli", label, found, f"已安装：{found}" if found else "未安装", None if found else _cli_install_fix(cli, which))
        # 中枢模型：岗位包选「中枢模型」时，命令行 agent 必须真的走中枢下发的模型（models.json 里有，且默认模型没被换掉）
        hub_model = (profile.get("model") or {}).get("model")
        if cli == "codebuddy" and hub_model:
            try:
                models = json.loads((home / "models.json").read_text(encoding="utf-8-sig")).get("models", [])
            except (OSError, ValueError):
                models = []
            ours = [m for m in models if str(m.get("name", "")).startswith(CB_MODEL_PREFIX)]
            try:
                default = json.loads((home / "settings.json").read_text(encoding="utf-8-sig")).get("model")
            except (OSError, ValueError):
                default = None
            if any(m.get("id") == hub_model for m in ours):
                other = default and default != hub_model and default not in {m.get("id") for m in ours}
                add("hub_model", "中枢模型", True,
                    f"{label} 已配置中枢模型 {hub_model}" + (f"（默认模型当前是 {default}，不是中枢的，浏览器任务可能不走中枢计量）" if other else ""), warn=bool(other))
            else:
                add("hub_model", "中枢模型", False, f"{label} 里没有中枢下发的模型 {hub_model}",
                    {"text": f"重新同步配置：uv run {Path(__file__).resolve()} sync（会写入 {home / 'models.json'}）",
                     "argv": [find_uv(), "run", str(Path(__file__).resolve()), "sync"]})
        else:
            add("hub_model", "中枢模型", True, "岗位包用自带模型（或尚未领取配置），不检查")
    if wants_browser:
        npx = which("npx")
        add("npx", "npx（运行 Playwright）", npx, f"已安装：{npx}" if npx else "未安装（随 Node.js 一起安装）",
            None if npx else {"text": "先安装 Node.js：" + _install_hint(), "argv": None})
        found = browser_finder()
        add("system_browser", "系统浏览器", found, f"已找到：{found}" if found else "没有找到 Edge 或 Chrome",
            None if found else {"text": CLI_MIN_BROWSER_FIXES, "argv": None})
        ver = requires.get("playwright_mcp")
        warm = bool(npx) and cached(ver)
        add("playwright_mcp", "Playwright MCP", True,
            "已在本机缓存" if warm else "首次使用要下载（约 1-2 分钟，期间浏览器任务会显示「仍在连接中」）",
            None if warm or not npx else {"text": f"预热：npx -y @playwright/mcp{'@' + ver if ver else ''} --help",
                                          "argv": ["npx", "-y", f"@playwright/mcp{'@' + ver if ver else ''}", "--help"]}, warn=not warm)

    def cap(ids: list[str]) -> dict:
        bad = [c for c in checks if c["id"] in ids and not c["ok"]]
        return {"ready": not bad, "missing": [c["label"] for c in bad], "fixes": [c["fix"]["text"] for c in bad if c["fix"]]}
    caps = {}
    if cli:
        caps["agent_cli"] = cap(["agent_cli", "hub_model"])
    if wants_browser:
        caps["browser"] = cap(["agent_cli", "hub_model", "npx", "system_browser"])
    return {"checks": checks, "capabilities": caps, "missing": [c["label"] for c in checks if not c["ok"]]}


def write_capabilities(app_id: str, version: str, pf: dict) -> Path:
    f = CAPABILITIES_DIR / f"{app_id}.json"
    doc = {"schema": 1, "app_id": app_id, "version": version, "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "capabilities": pf["capabilities"], "checks": [{k: c[k] for k in ("id", "label", "ok", "warn", "detail")} for c in pf["checks"]]}
    write_private(f, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    return f


def capability_notice(app_id: str, pf: dict) -> str:
    """给 agent / 员工看的说明：缺什么、对应功能为什么不可用、怎么装。没有缺失返回空串。"""
    bad = [c for c in pf["checks"] if not c["ok"]]
    if not bad:
        warns = [c for c in pf["checks"] if c["warn"] and c["fix"] and c["fix"]["argv"]]
        return ("提示：" + "；".join(f"{c['label']}：{c['detail']}" for c in warns)
                + f"。想提前准备好，运行：uv run {Path(__file__).resolve()} app-doctor {app_id} --yes") if warns else ""
    lines = ["⚠ 应用已打开，但缺少下面的能力，对应功能（如浏览器自动化）暂时不可用：",
             *[f"- {c['label']}：{c['detail']}" + (f" → {c['fix']['text']}" if c["fix"] else "") for c in bad]]
    fixable = [c for c in bad if c["fix"] and c["fix"]["argv"]]
    if fixable:
        lines.append(f"请先问员工是否同意安装；同意后执行：uv run {Path(__file__).resolve()} app-doctor {app_id} --yes ，装好后不用重启应用。")
    return "\n".join(lines)


def run_fix(fix: dict, run=subprocess.run) -> tuple[bool, str]:
    argv = list(fix["argv"])
    resolved = shutil.which(argv[0])
    if resolved:
        argv[0] = resolved
    try:
        r = run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()[-300:]


def cmd_app_doctor(args, ask=None, run=subprocess.run) -> None:
    """app-doctor <应用 id>：重新预检并（经询问）安装缺少的依赖，然后刷新能力文件。--yes 表示已征得员工同意，不再逐项询问。"""
    cached = HOME / "apps" / args.app_id / ".requires.json"
    try:
        meta = json.loads(cached.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fail(f"还没有打开过应用 {args.app_id}。请先对 agent 说「打开它」，再运行本命令。")
    pf = preflight(meta.get("requires") or {})
    interactive = sys.stdin.isatty() if ask is None else True
    ask = ask or (lambda q: input(q).strip().lower() in ("y", "yes"))
    for c in [c for c in pf["checks"] if not c["ok"] or (c["warn"] and c["fix"] and c["fix"]["argv"])]:
        fix = c["fix"]
        info(f"{c['label']}：{c['detail']}")
        if not fix or not fix["argv"]:
            info(f"  需要手动处理：{fix['text'] if fix else '（无）'}")
            continue
        if args.yes or (interactive and ask(f"  现在执行「{fix['text']}」吗？[y/N] ")):
            ok, out = run_fix(fix, run)
            info(f"  {'完成' if ok else '失败：' + out}")
        else:
            info(f"  已跳过。想自己装：{fix['text']}")
    pf = preflight(meta.get("requires") or {})
    f = write_capabilities(args.app_id, meta.get("version", ""), pf)
    notice = capability_notice(args.app_id, pf)
    info(notice or "所有能力都满足，应用里的对应功能已可用。")
    info(f"能力文件：{f}")


def launch_app(ticket: dict, hub: str, creds: dict, run=subprocess.run, client: httpx.Client | None = None) -> dict:
    """按中枢签发的凭证在本机打开应用：检查 Node → 下载校验解压（已有同版本同哈希则复用）→ 启动 → 取回网址。
    正在运行的实例绝不重启：应用的 start 是幂等的，已在运行时只返回同一个网址，新版本只给升级提示。"""
    app_id, version = ticket["app_id"], ticket["version"]
    try:
        ok, node = node_status(ticket.get("requires") or {}, run=run)
        if not ok:
            return {"ok": False, "reason": node}
        with _app_lock(app_id):
            target = app_dir(app_id, version)
            marker = target / ".sha256"
            if not (target.is_dir() and marker.exists() and marker.read_text().strip() == ticket["sha256"]):
                http = client or httpx.Client(follow_redirects=True)
                zip_file = fetch_verified(ticket["download_url"], ticket["sha256"], HOME / "apps" / app_id / ".downloads" / f"{version}.zip", http)
                shutil.rmtree(target, ignore_errors=True)
                safe_extract(zip_file, target)
                zip_file.unlink(missing_ok=True)
                marker.write_text(ticket["sha256"])
            entry = (target / ticket["entry"]).resolve()
            if target.resolve() not in entry.parents or not entry.is_file():
                return {"ok": False, "reason": f"应用入口不在应用包内或不存在：{ticket['entry']}"}
            env = {**os.environ, "HUB_MCP_SERVERS_FILE": str(_write_hub_mcp_config()),
                   "HUB_TRACE_ID": os.environ.get("HUB_TRACE_ID") or new_trace_id()}
            env["HUB_WORK_OUTBOX"] = str(outbox_file(app_id))  # 应用把关键产出追加写到这里，接入器转发给中枢（中枢上的「工作看板」）
            outbox_dir().mkdir(parents=True, exist_ok=True)
            requires = ticket.get("requires") or {}
            pf = preflight(requires) if (requires.get("agent_cli") or requires.get("capabilities")) else None
            if pf:  # 记下 requires 供 app-doctor 复核；能力文件交给应用，缺什么应用自己禁用对应功能
                write_private(HOME / "apps" / app_id / ".requires.json", json.dumps({"requires": requires, "version": version}, ensure_ascii=False))
                env["HUB_CAPABILITIES_FILE"] = str(write_capabilities(app_id, version, pf))
            base = {"cwd": str(target), "env": env, "capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}
            try:
                setup_out = ""
                if ticket.get("setup_args"):
                    done = run(["node", str(entry), *ticket["setup_args"]], timeout=LAUNCH_TIMEOUT, **base)
                    setup_out = (done.stdout or "") + (done.stderr or "")
                started = run(["node", str(entry), *ticket.get("start_args", [])], timeout=LAUNCH_TIMEOUT, **base)
            except subprocess.TimeoutExpired:
                return {"ok": False, "reason": f"启动超时（{LAUNCH_TIMEOUT} 秒）。可以稍后再说一次「打开工作台」，仍不行请查看应用自己的日志。"}
            out = (started.stdout or "") + (started.stderr or "")
            url = parse_url(out)
            if not url:
                return {"ok": False, "reason": "应用没有返回网址。输出：" + (out.strip()[-300:] or "（空）")}
            state_file = HOME / "apps" / app_id / ".running.json"
            old = json.loads(state_file.read_text(encoding="utf-8")).get("version") if state_file.exists() else None
            message = f"已打开「{ticket.get('name', app_id)}」v{version}：{url}"
            skill = target / "xhs-workbench" / "SKILL.md" if (target / "xhs-workbench" / "SKILL.md").exists() else next(iter(target.glob("*/SKILL.md")), None)
            if "尚未配置" in setup_out:  # 网页右上角会显示「未连接 agent」，要 agent 先做连接自检
                message += (f"\n工作台还没有连接 agent（网页会显示「未连接 agent」）。请现在做连接自检：运行 "
                            f"node \"{entry}\" bridge-test --inbox（你是 claude-code / codex 等有命令行的 agent 时改用 "
                            f"--prefer <你的 id>），详见 {skill or 'SKILL.md'} 的「连接自检」一节；"
                            "完成后若是收件箱模式，继续进入值守，网页里的消息才会被处理。")
            elif skill:
                message += f"\n如果它的连接模式是「收件箱模式」，请按 {skill} 的「值守模式」一节进入值守。"
            if _ALREADY in out and old and old != version:
                message += f"\n注意：正在运行的是旧版本 v{old}，新版本 v{version} 已下载；关闭工作台后再打开即可升级（为避免打断定时任务，没有自动重启）。"
            elif _STARTED in out or not old:
                state_file.write_text(json.dumps({"version": version}), encoding="utf-8")
            prune_versions(app_id)
            notice = capability_notice(app_id, pf) if pf else ""
            if notice:
                message += "\n" + notice
            return {"ok": True, "url": url, "version": version, "dir": str(target), "message": message,
                    "missing": pf["missing"] if pf else []}
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    except OSError as e:
        return {"ok": False, "reason": f"本机操作失败：{e}"}


# ---------------- 应用成果自动上报（outbox） ----------------

OUTBOX_DIR: Path | None = None  # 默认 HOME/outbox，测试里可替换
OUTBOX_ALLOWED = ("key", "title", "kind", "status", "progress", "link", "note")
OUTBOX_MAX_LINE = 4096
OUTBOX_BATCH = 50
OUTBOX_SECONDS = 20


def outbox_dir() -> Path:
    return OUTBOX_DIR or HOME / "outbox"


def outbox_file(app_id: str) -> Path:
    return outbox_dir() / f"{app_id}.jsonl"


def _outbox_items(chunk: bytes) -> list[dict]:
    """把一段完整的行解析成待上报条目：坏行、过长的行、缺 key / 标题的行直接丢掉，字段只保留白名单。"""
    out = []
    for line in chunk.splitlines():
        if not line.strip() or len(line) > OUTBOX_MAX_LINE:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("key") and d.get("title"):
            out.append({k: d[k] for k in OUTBOX_ALLOWED if k in d})
    return out


def flush_outbox(creds: dict, hub: str, app_id: str | None = None, post=None) -> int:
    """把应用写在本机 outbox 里的新成果转发给中枢，返回转发条数。
    按字节偏移记进度（<app>.offset），只处理完整的行；网络 / 5xx 失败时不推进，下次重试；
    中枢按 (人, 应用, key) 幂等，所以重复转发（比如两个桥同时在跑）只是更新。"""
    if app_id:
        files = [outbox_file(app_id)] if outbox_file(app_id).exists() else []
    else:
        files = sorted(outbox_dir().glob("*.jsonl")) if outbox_dir().is_dir() else []
    post = post or (lambda aid, items: httpx.post(
        f"{hub}/api/agent/work-report", timeout=15, json={"app_id": aid, "items": items},
        headers={"Authorization": f"Bearer {creds['access_token']}", "X-Hub-Trace-Id": os.environ.get("HUB_TRACE_ID", "")}))
    sent = 0
    for f in files:
        aid = f.stem
        if not APP_ID_RE.match(aid):
            continue
        off_file = f.with_suffix(".offset")
        try:
            offset = int(off_file.read_text().strip() or 0) if off_file.exists() else 0
            size = f.stat().st_size
            if size < offset:  # 文件被清空 / 换过：从头来
                offset = 0
            if size == offset:
                continue
            with f.open("rb") as fh:
                fh.seek(offset)
                data = fh.read(1024 * 1024)
        except (OSError, ValueError):
            continue
        end = data.rfind(bytes([10])) + 1  # 只处理到最后一个换行：最后半行可能还没写完
        if end == 0:
            continue
        lines = data[:end].splitlines(keepends=True)
        pos = offset
        batch, batch_bytes = [], 0
        for ln in lines + [None]:
            if ln is not None:
                batch.extend(_outbox_items(ln))
                batch_bytes += len(ln)
            if ln is None or len(batch) >= OUTBOX_BATCH:
                if batch:
                    try:
                        r = post(aid, batch[:OUTBOX_BATCH])
                    except Exception as e:  # noqa: BLE001 网络不通：保持偏移，下次再试
                        print(f"hub-agent: 转发成果失败：{e}", file=sys.stderr, flush=True)
                        return sent
                    if r.status_code >= 500 or r.status_code in (401, 429):
                        print(f"hub-agent: 转发成果失败：HTTP {r.status_code}", file=sys.stderr, flush=True)
                        return sent
                    sent += len(batch) if r.status_code == 200 else 0  # 其他 4xx：这批有问题，跳过，不卡住后面的
                    batch = batch[OUTBOX_BATCH:]
                pos += batch_bytes
                batch_bytes = 0
                try:
                    write_private(off_file, str(pos))
                except OSError:
                    return sent
    return sent


def cmd_flush_outbox(args) -> None:
    """flush-outbox [应用 id]：立刻转发应用写在本机的成果（桥运行时会每 20 秒自动转发）。"""
    creds = fresh_creds()
    n = flush_outbox(creds, creds["hub"], getattr(args, "app_id", None))
    info(f"已向中枢转发 {n} 条工作成果。")


def _outbox_loop() -> None:
    while True:
        time.sleep(OUTBOX_SECONDS)
        try:
            creds = fresh_creds()
            flush_outbox(creds, creds["hub"])
        except (Exception, SystemExit) as e:  # noqa: BLE001 转发失败不影响桥
            print(f"hub-agent mcp: 转发成果失败：{e}", file=sys.stderr, flush=True)


def report_app_event(creds: dict, hub: str, ticket: dict, result: dict) -> None:
    """把启动结果回报给中枢写审计；失败只写 stderr，不影响使用。"""
    try:
        httpx.post(f"{hub}/api/agent/app-event", timeout=10,
                   headers={"Authorization": f"Bearer {creds['access_token']}", "X-Hub-Trace-Id": os.environ.get("HUB_TRACE_ID", "")},
                   json={"app_id": ticket["app_id"], "version": ticket.get("version", ""), "ok": bool(result.get("ok")),
                         "url": result.get("url", ""), "reason": result.get("reason", ""), "missing": result.get("missing", [])})
    except Exception as e:  # noqa: BLE001
        print(f"hub-agent: 回报应用事件失败：{e}", file=sys.stderr, flush=True)


def cmd_open_app(args) -> None:
    """open-app <应用 id>：向中枢取启动凭证并在本机打开（给不走 MCP 桥的客户端，如 Hermes）。"""
    creds = fresh_creds()
    os.environ.setdefault("HUB_TRACE_ID", new_trace_id())
    r = httpx.post(f"{creds['hub']}/api/agent/open-app", timeout=30, json={"app_id": args.app_id},
                   headers={"Authorization": f"Bearer {creds['access_token']}", "X-Hub-Trace-Id": os.environ["HUB_TRACE_ID"]})
    if r.status_code != 200:
        fail(r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text)
    ticket = r.json()
    result = launch_app(ticket, creds["hub"], creds)
    report_app_event(creds, creds["hub"], ticket, result)
    if not result["ok"]:
        fail(result["reason"])
    info(result["message"])
    info("提示：工作台产生的成果会由 `hub_agent.py flush-outbox` 转发到中枢；桥（MCP）运行时会自动转发。")


# ---------------- 本地 MCP 桥 ----------------

def _post_mcp(http: httpx.Client, url: str, msg: dict, headers: dict) -> httpx.Response:
    creds = fresh_creds()  # 令牌快过期时自动续期
    return http.post(url, json=msg, headers={**headers, "Authorization": f"Bearer {creds['access_token']}"})


def parse_response(resp: httpx.Response) -> list[dict]:
    """把中枢的回复拆成 JSON-RPC 消息列表：JSON 直接解析，SSE 流按事件累积 data 行；202（通知确认）为空。"""
    if resp.status_code == 202 or not resp.content:
        return []
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        msgs, data = [], []
        for line in resp.text.splitlines() + [""]:
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line and data:
                msgs.append(json.loads("".join(data)))
                data = []
        return msgs
    return [json.loads(resp.content)]


def _write_messages(msgs: list[dict], out) -> None:
    for m in msgs:
        out.write((json.dumps(m, ensure_ascii=False) + "\n").encode("utf-8"))
    out.flush()


def _tool_text(msg: dict) -> str:
    return "".join(c.get("text", "") for c in (msg.get("result") or {}).get("content", []) if isinstance(c, dict))


def bridge_intercept(msg: dict, resp_msgs: list[dict], launch, hub: str, creds: dict, report) -> list[dict] | None:
    """拦截 open_app：中枢返回启动凭证时，在本机完成启动并用结果替换回复；
    中枢拒绝（纯文本）或协议错误则原样透传，绝不吞掉。不是 open_app 返回 None。"""
    if msg.get("method") != "tools/call" or (msg.get("params") or {}).get("name") != "open_app":
        return None
    for m in resp_msgs:
        if m.get("id") != msg.get("id") or "result" not in m:
            continue
        try:
            ticket = json.loads(_tool_text(m))
        except ValueError:
            return resp_msgs  # 拒绝提示（纯文本）
        if not isinstance(ticket, dict) or not ticket.get("needs_local_connector"):
            return resp_msgs
        result = launch(ticket, hub, creds)
        report(creds, hub, ticket, result)
        text = result["message"] if result.get("ok") else f"没能打开「{ticket.get('name', ticket.get('app_id'))}」：{result.get('reason', '未知原因')}"
        return [{"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": text}], "structuredContent": {"result": text}, "isError": not result.get("ok")}}]
    return resp_msgs


def _relay(resp: httpx.Response, out) -> None:
    """把中枢的回复写给桌面智能体。"""
    _write_messages(parse_response(resp), out)


HEARTBEAT_SECONDS = 60


def heartbeat_payload(client: str) -> dict:
    system = {"Darwin": "macOS"}.get(platform.system(), platform.system())
    release = platform.release() if system == "Windows" else ""
    return {"client": client, "version": VERSION, "os": f"{system} {release}".strip()}


def _heartbeat_loop(client: str) -> None:
    """桥接运行期间每分钟向中枢报到一次，控制台据此显示员工 agent 在线。失败不影响桥接。"""
    while True:
        try:
            creds = fresh_creds()
            httpx.post(f"{creds['hub']}/api/agent/heartbeat", json=heartbeat_payload(client), timeout=10,
                       headers={"Authorization": f"Bearer {creds['access_token']}"})
        except (Exception, SystemExit) as e:  # noqa: BLE001
            print(f"hub-agent mcp: 报到失败：{e}", file=sys.stderr, flush=True)
        time.sleep(HEARTBEAT_SECONDS)


def bridge_headers() -> dict:
    """桥发给中枢的固定请求头。追踪 ID 优先沿用环境变量 HUB_TRACE_ID（open_app 启动的工作台里的桥继承它，
    这样工作台里发起的调用与「打开应用」落在同一条审计链路里）。"""
    return {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
            "X-Hub-Trace-Id": os.environ.get("HUB_TRACE_ID") or new_trace_id(), "X-Hub-Task": quote("桌面智能体会话")}


def cmd_mcp(args=None) -> None:
    """stdio ↔ 中枢 MCP（Streamable HTTP）的桥。stdout 只输出协议消息，日志写 stderr。
    嵌套模式（--nested 或 HUB_BRIDGE_NESTED=1）：由已接入的应用里的 agent 启动，不再同步技能、不报心跳。"""
    log_to_stderr()
    nested = bool(getattr(args, "nested", False)) or os.environ.get("HUB_BRIDGE_NESTED") == "1"
    client = getattr(args, "client", None) or "桌面 agent"
    if not nested:
        try:  # 每次桌面智能体启动时拉一次最新的岗位包技能
            cmd_sync()
        except (Exception, SystemExit) as e:  # noqa: BLE001 同步失败不影响桥本身
            print(f"hub-agent mcp: 同步技能失败：{e}", file=sys.stderr, flush=True)
        threading.Thread(target=_heartbeat_loop, args=(client,), daemon=True).start()
        threading.Thread(target=_outbox_loop, daemon=True).start()
    creds = fresh_creds()
    mcp_url = httpx.get(f"{creds['hub']}/api/agent/config", timeout=15).json()["mcp_url"]
    headers = bridge_headers()
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
                replaced = bridge_intercept(msg, parse_response(resp), launch_app, creds["hub"], creds, report_app_event)
                _write_messages(replaced if replaced is not None else parse_response(resp), out)
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
    p = sub.add_parser("setup", help="一键接入：登录并自动配置本机的 WorkBuddy / Cursor / Claude 桌面版")
    p.add_argument("--hub", required=True, help="中枢控制台地址，如 http://192.168.1.10:8088")
    sub.add_parser("sync", help="重新领取配置和技能")
    sub.add_parser("status", help="查看当前登录状态")
    sub.add_parser("logout", help="退出并清除本机凭证")
    sub.add_parser("chat", help="启动 Hermes（其余参数原样传给 hermes）")
    p = sub.add_parser("mcp", help="本地 MCP 桥（stdio），给 WorkBuddy 等桌面智能体用")
    p.add_argument("--client", default="", help="桌面 agent 的名称（用于控制台显示在线状态）")
    p.add_argument("--nested", action="store_true", help="嵌套模式：由应用里的 agent 启动，不同步技能、不报心跳")
    p = sub.add_parser("open-app", help="在本机打开中枢发布的应用（给不走 MCP 桥的客户端用）")
    p.add_argument("app_id", help="应用 id，如 xhs-workbench")
    p = sub.add_parser("app-doctor", help="重新检查应用需要的依赖，并（经询问）安装缺少的部分")
    p.add_argument("app_id", help="应用 id，如 xhs-workbench")
    p.add_argument("--yes", action="store_true", help="已征得员工同意，不再逐项询问")
    p = sub.add_parser("flush-outbox", help="把应用写在本机的工作成果转发到中枢（桥运行时会自动转发）")
    p.add_argument("app_id", nargs="?", default=None, help="只转发这个应用；省略则转发全部")
    # chat 后面的参数（如 -q、--resume）全部原样交给 hermes，不经过本程序解析
    if len(sys.argv) > 1 and sys.argv[1] == "chat":
        return cmd_chat(argparse.Namespace(hermes_args=sys.argv[2:]))
    args = ap.parse_args()
    {"login": cmd_login, "setup": cmd_setup, "sync": cmd_sync, "status": cmd_status, "logout": cmd_logout, "chat": cmd_chat,
     "mcp": cmd_mcp, "open-app": cmd_open_app, "app-doctor": cmd_app_doctor, "flush-outbox": cmd_flush_outbox}[args.cmd](args)


if __name__ == "__main__":
    main()
