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
import webbrowser
from pathlib import Path

import httpx
import yaml

HOME = Path(os.environ.get("HUB_AGENT_HOME", Path.home() / ".hub-agent"))
CREDS = HOME / "credentials.json"
HERMES_HOME = HOME / "hermes"
SKILLS_DIR = HOME / "skills"
CALLBACK_PORT = 27891


def info(msg: str) -> None:
    print(f"\033[36m›\033[0m {msg}")


def fail(msg: str) -> None:
    print(f"\033[31m✗\033[0m {msg}", file=sys.stderr)
    sys.exit(1)


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o600)


# ---------------- 登录 ----------------

def load_creds() -> dict:
    if not CREDS.exists():
        fail("尚未登录，请先运行：hub_agent.py login --hub http://<中枢地址>:8088")
    return json.loads(CREDS.read_text())


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

def cmd_sync(_args=None) -> dict:
    creds = fresh_creds()
    r = httpx.post(f"{creds['hub']}/api/agent/enroll", headers={"Authorization": f"Bearer {creds['access_token']}"},
                   timeout=30)
    if r.status_code != 200:
        fail(f"领取配置失败：{r.json().get('detail', r.text)}")
    cfg = r.json()

    # 技能：先清空再写入，岗位包里撤掉的技能会随之消失
    if SKILLS_DIR.exists():
        shutil.rmtree(SKILLS_DIR)
    for s in cfg["skills"]:
        p = SKILLS_DIR / s["id"] / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(s["content"] or "")

    # Hermes 配置：这个目录由接入器管理，每次同步整体重写
    env = {"HUB_AGENT_TOKEN": creds["access_token"]}
    conf: dict = {
        "mcp_servers": {"hub": {"url": cfg["mcp_url"], "headers": {"Authorization": "Bearer ${HUB_AGENT_TOKEN}"}}},
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

    e = cfg["employee"]
    info(f"{e['name']}（{e['role_pack']}）：已同步技能 {len(cfg['skills'])} 个"
         + (f"，模型 {cfg['model']['model']}" if cfg.get("model") else "，中枢未下发模型"))
    write_private(HOME / "profile.json", json.dumps(cfg | {"skills": [s["id"] for s in cfg["skills"]]},
                                                    ensure_ascii=False, indent=2))
    return cfg


def cmd_status(_args) -> None:
    creds = load_creds()
    left = int(creds["expires_at"] - time.time())
    prof = json.loads((HOME / "profile.json").read_text()) if (HOME / "profile.json").exists() else {}
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
    cmd_sync()
    hermes = shutil.which("hermes")
    if not hermes:
        fail("没有找到 hermes 命令，请先安装 Hermes Agent")
    os.execvpe(hermes, [hermes, "chat", *args.hermes_args], {**os.environ, "HERMES_HOME": str(HERMES_HOME)})


def main() -> None:
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
    # chat 后面的参数（如 -q、--resume）全部原样交给 hermes，不经过本程序解析
    if len(sys.argv) > 1 and sys.argv[1] == "chat":
        return cmd_chat(argparse.Namespace(hermes_args=sys.argv[2:]))
    args = ap.parse_args()
    {"login": cmd_login, "sync": cmd_sync, "status": cmd_status, "logout": cmd_logout, "chat": cmd_chat}[args.cmd](args)


if __name__ == "__main__":
    main()
