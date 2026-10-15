"""开发环境用：在本地 Casdoor 里建好控制台需要的组织、应用、部门和测试成员。

模拟「钉钉组织架构同步到 Casdoor 之后」的状态。生产环境的部门和成员来自钉钉同步，不需要运行本脚本。
可重复运行：已存在的对象会跳过。

运行：cd console/backend && uv run python scripts/casdoor_dev_seed.py
读取 hub/.env 里的 CASDOOR_ORIGIN、CASDOOR_ADMIN_PASSWORD；
把控制台需要的配置写入 console/backend/.env，把测试组织管理员密码写入 hub/.env（XINGHE_ADMIN_PASSWORD）。
"""

from __future__ import annotations

import copy
import secrets
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
HUB_ENV = ROOT / "hub" / ".env"
CONSOLE_ENV = ROOT / "console" / "backend" / ".env"

ORG = "xinghe"
ORG_DISPLAY = "星河品牌（演示）"
APP = "hub-console"
CONSOLE_URL = "http://localhost:5173"

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
    path.chmod(0o600)


def main() -> None:
    hub = dotenv_values(HUB_ENV)
    endpoint = hub.get("CASDOOR_ORIGIN") or die("hub/.env 缺少 CASDOOR_ORIGIN")
    admin_pw = hub.get("CASDOOR_ADMIN_PASSWORD") or die("hub/.env 缺少 CASDOOR_ADMIN_PASSWORD")
    org_admin_pw = hub.get("XINGHE_ADMIN_PASSWORD") or secrets.token_urlsafe(12)

    c = httpx.Client(base_url=endpoint, timeout=15)
    ok(c.post("/api/login", json={
        "application": "app-built-in", "organization": "built-in", "username": "admin",
        "password": admin_pw, "type": "login", "signinMethod": "Password",
    }), "登录 built-in/admin")
    print(f"✓ 已登录 {endpoint}")

    # ---- 组织 ----
    if c.get("/api/get-organization", params={"id": f"admin/{ORG}"}).json().get("data"):
        print(f"· 组织 {ORG} 已存在")
    else:
        base = ok(c.get("/api/get-organization", params={"id": "admin/built-in"}), "读取 built-in 组织")["data"]
        org = copy.deepcopy(base)
        org.update({"name": ORG, "displayName": ORG_DISPLAY, "passwordType": "bcrypt",
                    "websiteUrl": "", "defaultApplication": APP, "languages": ["zh", "en"]})
        ok(c.post("/api/add-organization", json=org), "创建组织")
        print(f"✓ 创建组织 {ORG}")

    # ---- 应用（OAuth 客户端）----
    redirect_uris = [f"{CONSOLE_URL}/callback", CONSOLE_URL]  # 后者用于退出登录后跳回
    app = c.get("/api/get-application", params={"id": f"admin/{APP}"}).json().get("data")
    if app:
        if app.get("redirectUris") != redirect_uris:
            app["redirectUris"] = redirect_uris
            ok(c.post("/api/update-application", params={"id": f"admin/{APP}"}, json=app), "更新应用回调地址")
        print(f"· 应用 {APP} 已存在")
    else:
        base = ok(c.get("/api/get-application", params={"id": "admin/app-built-in"}), "读取 app-built-in")["data"]
        app = copy.deepcopy(base)
        for k in ("organizationObj", "certPublicKey"):
            app.pop(k, None)
        app.update({
            "name": APP, "displayName": "智能体中枢控制台", "organization": ORG,
            "clientId": secrets.token_hex(10), "clientSecret": secrets.token_hex(20),
            "redirectUris": redirect_uris, "grantTypes": ["authorization_code", "refresh_token"],
            "enableSignUp": False, "homepageUrl": CONSOLE_URL, "expireInHours": 24, "refreshExpireInHours": 168,
        })
        ok(c.post("/api/add-application", json=app), "创建应用")
        print(f"✓ 创建应用 {APP}")

    # ---- 部门（Casdoor 分组）----
    existing = {g["name"] for g in (c.get("/api/get-groups", params={"owner": ORG}).json().get("data") or [])}
    for name, display in DEPARTMENTS:
        if name in existing:
            continue
        ok(c.post("/api/add-group", json={
            "owner": ORG, "name": name, "displayName": display, "type": "Physical",
            "parentId": ORG, "isTopGroup": True, "isEnabled": True,
        }), f"创建部门 {display}")
    print(f"✓ 部门 {len(DEPARTMENTS)} 个")

    # ---- 成员 ----
    users = {u["name"] for u in (c.get("/api/get-users", params={"owner": ORG}).json().get("data") or [])}
    created = 0
    for name, display, dept, title in USERS:
        if name in users:
            continue
        ok(c.post("/api/add-user", json={
            "owner": ORG, "name": name, "displayName": display, "title": title,
            "groups": [f"{ORG}/{dept}"], "password": secrets.token_urlsafe(16),
            "signupApplication": APP, "type": "normal-user", "properties": {},
        }), f"创建成员 {display}")
        created += 1
    if "admin" not in users:
        ok(c.post("/api/add-user", json={
            "owner": ORG, "name": "admin", "displayName": "管理员", "title": "系统管理员",
            "groups": [f"{ORG}/ceo"], "password": org_admin_pw, "isAdmin": True,
            "signupApplication": APP, "type": "normal-user", "properties": {},
        }), "创建组织管理员")
        created += 1
    print(f"✓ 成员 {len(USERS) + 1} 人（本次新建 {created}）")

    app = ok(c.get("/api/get-application", params={"id": f"admin/{APP}"}), "读取应用")["data"]
    upsert_env(CONSOLE_ENV, {
        "HUB_CONSOLE_MODE": "casdoor",
        "CASDOOR_ENDPOINT": endpoint,
        "CASDOOR_ORG": ORG,
        "CASDOOR_APP": APP,
        "CASDOOR_CLIENT_ID": app["clientId"],
        "CASDOOR_CLIENT_SECRET": app["clientSecret"],
        "CONSOLE_PUBLIC_URL": CONSOLE_URL,
    })
    upsert_env(HUB_ENV, {"XINGHE_ADMIN_PASSWORD": org_admin_pw})
    print("✓ 已写入 console/backend/.env")
    print(f"✓ 控制台管理员：{ORG}/admin，密码见 hub/.env 的 XINGHE_ADMIN_PASSWORD")


if __name__ == "__main__":
    main()
