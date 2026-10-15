"""初始化模型网关 New API（可重复运行）。

- 首次运行时创建管理员（密码 NEWAPI_ADMIN_PASSWORD，自用模式：不做计费，只记用量）
- 取得管理员的系统访问令牌，写回 hub/.env（NEWAPI_ACCESS_TOKEN、NEWAPI_ADMIN_ID），中枢用它给员工发 key、读用量
- --demo：再创建一个指向模拟模型（mock-llm）的渠道（模型 hub-mock、hub-mock-pro），HUB_DEFAULT_MODEL 设为 hub-mock，
  并把 hub-mock 加入除「财务」以外的岗位包（财务只允许本地模型，用来演示「没有可用模型」）

生产环境请在 New API 后台（http://<中枢>:3000）自行添加真实的模型渠道，并在 .env 里设置 HUB_DEFAULT_MODEL。

部署时由 make bootstrap 在容器内调用：
    python scripts/newapi_bootstrap.py --env-file /hub.env --newapi-url http://new-api:3000 [--demo]
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from casdoor_bootstrap import upsert_env  # noqa: E402

ADMIN_USER = "hubadmin"
MOCK_CHANNEL = "hub-mock"
MOCK_MODELS = "hub-mock,hub-mock-pro"


def die(msg: str) -> None:
    print(f"✗ {msg}")
    sys.exit(1)


def ok(r: httpx.Response, what: str) -> object:
    body = r.json()
    if not body.get("success"):
        die(f"{what} 失败：{body.get('message')}")
    return body.get("data")


def add_mock_model_to_packs() -> None:
    """演示环境：除财务外的岗位包都能用 hub-mock（hub-mock-pro 不加，用来演示模型白名单）。"""
    from app import db

    db.init_schema()
    changed = 0
    for rp in db.role_packs():
        if rp["id"] != "rp-finance" and "hub-mock" not in rp["models"]:
            db.upsert_role_pack(rp["id"], {**rp, "models": [*rp["models"], "hub-mock"]})
            changed += 1
    print(f"✓ 已把 hub-mock 加入 {changed} 个岗位包（财务除外）")


def main() -> None:
    ap = argparse.ArgumentParser(description="初始化 New API")
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--newapi-url", default="http://new-api:3000")
    ap.add_argument("--demo", action="store_true", help="创建指向模拟模型的渠道（仅开发/演示）")
    args = ap.parse_args()

    env_path = Path(args.env_file)
    env = dotenv_values(env_path)
    password = env.get("NEWAPI_ADMIN_PASSWORD") or secrets.token_urlsafe(14)
    c = httpx.Client(base_url=args.newapi_url, timeout=15)

    setup = ok(c.get("/api/setup"), "读取初始化状态")
    if not setup.get("status"):
        ok(c.post("/api/setup", json={"username": ADMIN_USER, "password": password, "confirmPassword": password,
                                       "SelfUseModeEnabled": True, "DemoSiteEnabled": False}), "初始化管理员")
        print(f"✓ 创建 New API 管理员 {ADMIN_USER}（自用模式）")
    else:
        print("· New API 已初始化")

    user = ok(c.post("/api/user/login", json={"username": ADMIN_USER, "password": password}), "管理员登录")
    admin_id = str(user["id"])
    c.headers["New-Api-User"] = admin_id
    access = ok(c.get("/api/user/token"), "生成系统访问令牌")
    print("✓ 已取得管理员访问令牌")

    values = {"NEWAPI_ADMIN_PASSWORD": password, "NEWAPI_ACCESS_TOKEN": access, "NEWAPI_ADMIN_ID": admin_id}

    if args.demo:
        api = httpx.Client(base_url=args.newapi_url, timeout=15,
                           headers={"Authorization": access, "New-Api-User": admin_id})
        data = ok(api.get("/api/channel/", params={"p": 1, "page_size": 100}), "读取渠道")
        items = data.get("items", []) if isinstance(data, dict) else (data or [])
        existing = next((ch for ch in items if ch.get("name") == MOCK_CHANNEL), None)
        if existing:
            if existing.get("models") != MOCK_MODELS:
                ch = ok(api.get(f"/api/channel/{existing['id']}"), "读取渠道")
                ok(api.put("/api/channel/", json={**ch, "models": MOCK_MODELS}), "更新模拟渠道模型")
            print(f"· 渠道 {MOCK_CHANNEL} 已存在")
        else:
            ok(api.post("/api/channel/", json={"mode": "single", "channel": {
                "type": 1, "name": MOCK_CHANNEL, "key": "sk-mock-not-a-real-key",
                "base_url": "http://mock-llm:8300", "models": MOCK_MODELS, "group": "default", "status": 1,
            }}), "创建模拟模型渠道")
            print(f"✓ 创建渠道 {MOCK_CHANNEL} → http://mock-llm:8300（{MOCK_MODELS}）")
        add_mock_model_to_packs()
        values["HUB_DEFAULT_MODEL"] = "hub-mock"
        # 没有配置 GPU 节点时，使用模拟 ComfyUI 节点
        if not env.get("HUB_GPU_NODES"):
            values["HUB_GPU_NODES"] = "gpu-01|GPU-01 模拟节点|http://mock-comfyui:8188|Mock GPU（开发用）"

    upsert_env(env_path, values)
    print(f"✓ 已写入 {env_path}")


if __name__ == "__main__":
    main()
