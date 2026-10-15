"""在 Casdoor 里准备中枢需要的组织和应用（可重复运行，已存在的对象会跳过或更新）。

基础部分（部署时必做）：
- 企业组织（HUB_ORG）
- 三个 OAuth 应用：hub-console（控制台登录）、hub-agent（员工端官方 agent）、hub-external（外部智能体）
- 把各应用的 client id / secret 写回 hub/.env，供 docker compose 使用

--demo（仅开发和演示）：再创建 9 个部门、18 名测试成员，并给 agent 应用开启 password 授权，便于脚本取令牌测试。
生产环境的部门和成员来自钉钉同步，不要加 --demo。

部署时（容器内运行，由 make bootstrap 调用）：
    python scripts/casdoor_bootstrap.py --env-file /hub.env --casdoor-url http://casdoor:8000 [--demo]
开发时（宿主机）：
    uv run python scripts/casdoor_bootstrap.py --demo --console-env .env
"""

from __future__ import annotations

import argparse
import copy
import secrets
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else Path("/")
DEV_CONSOLE_URL = "http://localhost:5173"

DEPARTMENTS = [
    ("ops", "运营部"), ("design", "设计部"), ("video", "视频部"), ("sales", "销售部"), ("cs", "客服部"),
    ("finance", "财务部"), ("hr", "人事行政部"), ("tech", "技术部"), ("ceo", "总经办"),
]

# 用户名, 显示名, 部门, 职位
USERS = [
    ("linxiaoman", "林小满", "ops", "小红书运营主管"),
    ("zhouyinuo", "周一诺", "ops", "小红书运营"),
    ("chenruoxi", "陈若曦", "ops", "内容策划"),
    ("wangzihan", "王子涵", "ops", "社群运营"),
    ("heyutong", "何雨桐", "design", "设计主管"),
    ("songjiaqi", "宋佳琪", "design", "视觉设计师"),
    ("liangchenyang", "梁晨阳", "video", "剪辑师"),
    ("guohaoran", "郭浩然", "sales", "销售总监"),
    ("tangsiyuan", "唐思远", "sales", "大客户经理"),
    ("fengkexin", "冯可馨", "sales", "销售专员"),
    ("caoyiqi", "曹诗涵", "cs", "客服主管"),
    ("xujingyi", "许静怡", "finance", "财务经理"),
    ("dengwenbo", "邓文博", "finance", "会计"),
    ("pengwanting", "彭婉婷", "hr", "人事行政经理"),
    ("xiaomingzhe", "肖明哲", "tech", "技术负责人"),
    ("tianyuxuan", "田宇轩", "tech", "后端工程师"),
    ("dongjiahao", "董家豪", "ceo", "总经理"),
]


def die(msg: str) -> None:
    print(f"✗ {msg}")
    sys.exit(1)


def ok(r: httpx.Response, what: str) -> dict:
    body = r.json()
    if body.get("status") != "ok":
        die(f"{what} 失败：{body.get('msg')}")
    return body


def upsert_env(path: Path, values: dict[str, str]) -> None:
    """更新 .env 文件中的键，保留其他行。"""
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in values:
            lines[i] = f"{key}={values[key]}"
            seen.add(key)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # 容器内挂载的文件可能不允许改权限


def ensure_app(c: httpx.Client, org: str, name: str, display: str, redirect_uris: list[str],
               grant_types: list[str], homepage: str) -> dict:
    """创建或更新一个 Casdoor 应用（OAuth 客户端），返回应用信息。"""
    app = c.get("/api/get-application", params={"id": f"admin/{name}"}).json().get("data")
    if app:
        if app.get("redirectUris") != redirect_uris or app.get("grantTypes") != grant_types:
            app.update({"redirectUris": redirect_uris, "grantTypes": grant_types})
            ok(c.post("/api/update-application", params={"id": f"admin/{name}"}, json=app), f"更新应用 {name}")
        print(f"· 应用 {name} 已存在")
        return app
    base = ok(c.get("/api/get-application", params={"id": "admin/app-built-in"}), "读取 app-built-in")["data"]
    app = copy.deepcopy(base)
    for k in ("organizationObj", "certPublicKey"):
        app.pop(k, None)
    app.update({
        "name": name, "displayName": display, "organization": org,
        "clientId": secrets.token_hex(10), "clientSecret": secrets.token_hex(20),
        "redirectUris": redirect_uris, "grantTypes": grant_types,
        "enableSignUp": False, "homepageUrl": homepage, "expireInHours": 24, "refreshExpireInHours": 168,
    })
    ok(c.post("/api/add-application", json=app), f"创建应用 {name}")
    print(f"✓ 创建应用 {name}")
    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="在 Casdoor 中准备中枢的组织和应用")
    ap.add_argument("--env-file", default=str(ROOT / "hub" / ".env"), help="hub/.env 路径，读取配置并写回应用凭证")
    ap.add_argument("--casdoor-url", help="脚本访问 Casdoor 的地址，默认取 CASDOOR_ORIGIN")
    ap.add_argument("--demo", action="store_true", help="同时创建测试部门和成员（仅开发/演示）")
    ap.add_argument("--console-env", help="宿主机开发时，额外写入 console/backend/.env")
    args = ap.parse_args()

    env_path = Path(args.env_file)
    hub = dotenv_values(env_path)
    public = hub.get("CASDOOR_ORIGIN") or die("缺少 CASDOOR_ORIGIN")
    endpoint = (args.casdoor_url or public).rstrip("/")
    admin_pw = hub.get("CASDOOR_ADMIN_PASSWORD") or die("缺少 CASDOOR_ADMIN_PASSWORD")
    org_name = hub.get("HUB_ORG") or "xinghe"
    org_display = hub.get("HUB_ORG_DISPLAY") or org_name
    host = hub.get("HUB_HOST") or "localhost"
    console_url = f"http://{host}:{hub.get('CONSOLE_PORT') or '8088'}"
    org_admin_pw = hub.get("XINGHE_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    # 测试成员共用一个密码，便于用脚本模拟不同员工的 agent
    user_pw = hub.get("XINGHE_USER_PASSWORD") or secrets.token_urlsafe(12)

    c = httpx.Client(base_url=endpoint, timeout=15)
    ok(c.post("/api/login", json={
        "application": "app-built-in", "organization": "built-in", "username": "admin",
        "password": admin_pw, "type": "login", "signinMethod": "Password",
    }), "登录 built-in/admin")
    print(f"✓ 已登录 {endpoint}")

    # ---- 组织 ----
    if c.get("/api/get-organization", params={"id": f"admin/{org_name}"}).json().get("data"):
        print(f"· 组织 {org_name} 已存在")
    else:
        base = ok(c.get("/api/get-organization", params={"id": "admin/built-in"}), "读取 built-in 组织")["data"]
        org = copy.deepcopy(base)
        org.update({"name": org_name, "displayName": org_display, "passwordType": "bcrypt",
                    "websiteUrl": "", "defaultApplication": "hub-console", "languages": ["zh", "en"]})
        ok(c.post("/api/add-organization", json=org), "创建组织")
        print(f"✓ 创建组织 {org_name}")

    # ---- 应用（OAuth 客户端）----
    consoles = [console_url] + ([DEV_CONSOLE_URL] if args.demo else [])
    redirect_uris = [u for url in consoles for u in (f"{url}/callback", url)]  # 后者用于退出登录后跳回
    agent_grants = ["authorization_code", "refresh_token"] + (["password"] if args.demo else [])
    console_app = ensure_app(c, org_name, "hub-console", "智能体中枢控制台", redirect_uris,
                             ["authorization_code", "refresh_token"], console_url)
    # 员工端官方 agent 与外部智能体各用一个应用，MCP Server 按令牌来自哪个应用区分入口
    # 员工端在本机 127.0.0.1:27891 接收浏览器登录回调（授权码 + PKCE）
    agent_app = ensure_app(c, org_name, "hub-agent", "员工端 agent", ["http://127.0.0.1:27891/callback"],
                           agent_grants, console_url)
    external_app = ensure_app(c, org_name, "hub-external", "外部智能体（MCP 接入）", ["http://localhost/callback"],
                              agent_grants, console_url)

    if args.demo:
        seed_demo(c, org_name, org_admin_pw, user_pw)

    values = {
        "CASDOOR_CONSOLE_CLIENT_ID": console_app["clientId"],
        "CASDOOR_CONSOLE_CLIENT_SECRET": console_app["clientSecret"],
        "HUB_AGENT_CLIENT_ID": agent_app["clientId"],
        "HUB_AGENT_CLIENT_SECRET": agent_app["clientSecret"],
        "HUB_EXTERNAL_CLIENT_ID": external_app["clientId"],
        "HUB_EXTERNAL_CLIENT_SECRET": external_app["clientSecret"],
    }
    if args.demo:
        # COMPOSE_PROFILES=demo 让 docker compose 同时管理模拟模型服务
        values |= {"XINGHE_ADMIN_PASSWORD": org_admin_pw, "XINGHE_USER_PASSWORD": user_pw,
                   "HUB_AGENT_PASSWORD_LOGIN": "true", "COMPOSE_PROFILES": "demo"}
    upsert_env(env_path, values)
    print(f"✓ 应用凭证已写入 {env_path}")

    if args.console_env:
        upsert_env(Path(args.console_env), {
            "HUB_CONSOLE_MODE": "casdoor",
            "CASDOOR_ENDPOINT": endpoint,
            "CASDOOR_ORG": org_name,
            "CASDOOR_APP": "hub-console",
            "CASDOOR_CLIENT_ID": console_app["clientId"],
            "CASDOOR_CLIENT_SECRET": console_app["clientSecret"],
            "CONSOLE_PUBLIC_URL": DEV_CONSOLE_URL,
            "HUB_DATABASE_URL": f"postgresql://hub:{hub.get('HUB_DB_PASSWORD')}@127.0.0.1:{hub.get('POSTGRES_HOST_PORT') or '25432'}/hub",
            "HUB_AGENT_CLIENT_IDS": agent_app["clientId"],
            "HUB_EXTERNAL_CLIENT_IDS": external_app["clientId"],
        })
        print(f"✓ 开发配置已写入 {args.console_env}")
    if args.demo:
        print(f"✓ 控制台管理员：{org_name}/admin，密码见 {env_path.name} 的 XINGHE_ADMIN_PASSWORD；"
              "其他测试成员见 XINGHE_USER_PASSWORD")


def seed_demo(c: httpx.Client, org: str, admin_pw: str, user_pw: str) -> None:
    """创建测试部门和成员，模拟钉钉组织同步到 Casdoor 之后的状态。"""
    existing = {g["name"] for g in (c.get("/api/get-groups", params={"owner": org}).json().get("data") or [])}
    for name, display in DEPARTMENTS:
        if name not in existing:
            ok(c.post("/api/add-group", json={
                "owner": org, "name": name, "displayName": display, "type": "Physical",
                "parentId": org, "isTopGroup": True, "isEnabled": True,
            }), f"创建部门 {display}")
    print(f"✓ 部门 {len(DEPARTMENTS)} 个")

    users = {u["name"] for u in (c.get("/api/get-users", params={"owner": org}).json().get("data") or [])}
    created = 0
    for name, display, dept, title in USERS:
        if name in users:
            body = c.post("/api/set-password", data={"userOwner": org, "userName": name, "newPassword": user_pw}).json()
            # 密码没变时 Casdoor 会拒绝「设成相同密码」，这种情况视为成功
            if body.get("status") != "ok" and "different" not in (body.get("msg") or ""):
                die(f"重置 {display} 的密码失败：{body.get('msg')}")
            continue
        ok(c.post("/api/add-user", json={
            "owner": org, "name": name, "displayName": display, "title": title,
            "groups": [f"{org}/{dept}"], "password": user_pw,
            "signupApplication": "hub-console", "type": "normal-user", "properties": {},
        }), f"创建成员 {display}")
        created += 1
    if "admin" not in users:
        ok(c.post("/api/add-user", json={
            "owner": org, "name": "admin", "displayName": "管理员", "title": "系统管理员",
            "groups": [f"{org}/ceo"], "password": admin_pw, "isAdmin": True,
            "signupApplication": "hub-console", "type": "normal-user", "properties": {},
        }), "创建组织管理员")
        created += 1
    print(f"✓ 成员 {len(USERS) + 1} 人（本次新建 {created}）")


if __name__ == "__main__":
    main()
