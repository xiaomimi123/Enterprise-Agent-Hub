"""初始化 RAGFlow：注册管理员账号、创建 API Key，写回 hub/.env（RAGFLOW_API_KEY、RAGFLOW_ENDPOINT）。

用法（在中枢服务器上、RAGFlow 启动之后执行一次）：
    cd console/backend
    uv run python scripts/ragflow_bootstrap.py --env-file ../../hub/.env --url http://localhost:9380

管理员邮箱固定为 admin@hub.local，密码取 .env 里的 RAGFLOW_ADMIN_PASSWORD。已有 RAGFLOW_API_KEY 时不重复创建。
RAGFlow 的登录密码要用它自带的公钥做 RSA 加密（与网页前端一致），公钥随官方仓库在 hub/ragflow/upstream/conf/public.pem。
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

EMAIL = "admin@hub.local"
NICKNAME = "hubadmin"


def read_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_]+)=(.*)$", line.rstrip("\r"))
        if m:
            env[m.group(1)] = m.group(2)
    return env


def write_env(path: Path, values: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for k, v in values.items():
        if re.search(rf"^{k}=", text, re.M):
            text = re.sub(rf"^{k}=.*$", f"{k}={v}", text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{k}={v}\n"
    path.write_text(text, encoding="utf-8")


def encrypt_password(password: str, public_pem: bytes) -> str:
    """与 RAGFlow 前端一致：先 base64，再用公钥 RSA-PKCS1v15 加密，再 base64。"""
    key = serialization.load_pem_public_key(public_pem)
    inner = base64.b64encode(password.encode()).decode().encode()
    return base64.b64encode(key.encrypt(inner, padding.PKCS1v15())).decode()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK，打印 ✓ 会报错
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--url", default="http://localhost:9380", help="RAGFlow API 地址（本机访问）")
    ap.add_argument("--public-key", default=str(Path(__file__).resolve().parents[3] / "hub/ragflow/upstream/conf/public.pem"))
    args = ap.parse_args()

    env_path = Path(args.env_file)
    env = read_env(env_path)
    if env.get("RAGFLOW_API_KEY"):
        print("✓ .env 里已有 RAGFLOW_API_KEY，跳过")
        return
    password = env.get("RAGFLOW_ADMIN_PASSWORD")
    if not password:
        sys.exit("hub/.env 缺少 RAGFLOW_ADMIN_PASSWORD")
    enc = encrypt_password(password, Path(args.public_key).read_bytes())

    http = httpx.Client(base_url=args.url.rstrip("/"), timeout=30)
    body = {"email": EMAIL, "password": enc}
    r = http.post("/api/v1/users", json={**body, "nickname": NICKNAME})
    if r.json().get("code") == 0:
        print(f"✓ 注册管理员 {EMAIL}")
    else:
        print(f"· 注册未执行：{r.json().get('message')}")
    r = http.post("/api/v1/auth/login", json=body)
    if r.json().get("code") != 0:
        sys.exit(f"登录失败：{r.json().get('message')}")
    auth = r.headers.get("Authorization")
    print("✓ 登录成功")
    r = http.post("/api/v1/system/tokens", params={"name": "hub"}, headers={"Authorization": auth})
    data = r.json()
    if data.get("code") != 0:
        sys.exit(f"创建 API Key 失败：{data.get('message')}")
    write_env(env_path, {"RAGFLOW_API_KEY": data["data"]["token"], "RAGFLOW_ENDPOINT": "http://host.docker.internal:9380"})
    print(f"✓ API Key 已写入 {env_path}")


if __name__ == "__main__":
    main()
