"""把 vault/ 里的知识库灌进 RAGFlow（可重复运行，已存在的东西会跳过）。

步骤：
1. API key：.env 里已有 RAGFLOW_API_KEY 就直接用；没有则用 RAGFLOW_ADMIN_PASSWORD 登录
   RAGFlow（admin@ragflow.io）自动创建一个，写回 .env。自动创建失败时按提示去网页手动生成
2. 建库：vault/ 下每个文件夹建一个 dataset（名字 = 文件夹名 = 知识库名），内置 bge 中文向量模型
3. 传文档：每个库里的 *.md 上传（同名跳过），然后触发解析
4. 等解析完成，报告结果

部署时（容器内运行，由 make ragflow-bootstrap 调用）：
    python scripts/ragflow_bootstrap.py --env-file /hub.env
开发时（宿主机）：
    uv run python scripts/ragflow_bootstrap.py --env-file ../../hub/.env --vault-dir ../../vault \
        --ragflow-url http://<中枢IP>:9380
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ragflow  # noqa: E402
from app.config import settings  # noqa: E402

# RAGFlow 文档解析状态：0 未开始 / 1 进行中 / 2 取消 / 3 完成 / 4 失败 / 5 排队
DONE, FAIL, RUNNING = "3", "4", ("0", "1", "5")


def env_file_update(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")


def ensure_api_key(env: dict, env_path: Path, base: str) -> str:
    """拿到 RAGFlow API key：优先用 .env 里已有的，否则用管理员登录自动创建并写回 .env。"""
    if env.get("RAGFLOW_API_KEY"):
        return env["RAGFLOW_API_KEY"]
    password = env.get("RAGFLOW_ADMIN_PASSWORD") or "admin"
    with httpx.Client(base_url=base, timeout=30) as c:
        r = c.post("/api/v1/auth/login", json={"email": "admin@ragflow.io", "password": password}).json()
        if r.get("code") != 0:
            print(f"✗ 管理员登录失败：{r.get('message')}（密码应为 .env 的 RAGFLOW_ADMIN_PASSWORD）")
            print("  请到 RAGFlow 网页右上角头像 → API → 生成 API KEY，填入 hub/.env 的 RAGFLOW_API_KEY 后重跑")
            sys.exit(1)
        r = c.post("/api/v1/system/tokens", json={"name": "hub"}).json()
        if r.get("code") != 0 or not (r.get("data") or {}).get("token"):
            print(f"✗ 创建 API key 失败：{r.get('message')}")
            print("  请到 RAGFlow 网页右上角头像 → API → 生成 API KEY，填入 hub/.env 的 RAGFLOW_API_KEY 后重跑")
            sys.exit(1)
        key = r["data"]["token"]
    env_file_update(env_path, "RAGFLOW_API_KEY", key)
    print("✓ 已创建 RAGFlow API key 并写入 .env")
    return key


def main() -> None:
    ap = argparse.ArgumentParser(description="把 vault/ 知识库灌进 RAGFlow")
    ap.add_argument("--env-file", required=True, help="hub/.env 路径（读端口与密码，写回 RAGFLOW_API_KEY）")
    ap.add_argument("--vault-dir", help="知识库目录（默认用 HUB_VAULT_DIR 或仓库里的 vault/）")
    ap.add_argument("--ragflow-url", help="RAGFlow API 地址（默认 http://<HUB_HOST>:<RAGFLOW_API_PORT>）")
    ap.add_argument("--timeout", type=int, default=300, help="等解析完成的秒数")
    args = ap.parse_args()

    env_path = Path(args.env_file)
    env = {k: v for k, v in dotenv_values(env_path).items() if v}
    base = args.ragflow_url or f"http://{env.get('HUB_HOST', 'localhost')}:{env.get('RAGFLOW_API_PORT', '9380')}"
    # 容器里 HUB_VAULT_DIR 是镜像 ENV（/data/vault）；宿主机开发时用仓库里的 vault/
    _root = Path(__file__).resolve().parents
    vault = Path(args.vault_dir or os.environ.get("HUB_VAULT_DIR") or env.get("HUB_VAULT_DIR")
                 or (_root[3] / "vault" if len(_root) > 3 else _root[-1] / "vault"))
    if not vault.is_dir():
        sys.exit(f"✗ 知识库目录不存在：{vault}")

    key = ensure_api_key(env, env_path, base)
    # 客户端指向最终地址：bootstrap 时 .env 里可能还没写 RAGFLOW_API_KEY / RAGFLOW_ENDPOINT
    from dataclasses import replace
    ragflow.settings = replace(ragflow.settings, ragflow_endpoint=base, ragflow_api_key=key)
    ragflow._HTTP = None  # 用新配置重建客户端

    kb_dirs = sorted(d for d in vault.iterdir() if d.is_dir() and not d.name.startswith("."))
    print(f"RAGFlow {base}：准备灌入 {len(kb_dirs)} 个知识库（来自 {vault}）")
    for d in kb_dirs:
        ds_id = ragflow.create_dataset(d.name)
        existing = ragflow.documents(ds_id)
        files = sorted(d.rglob("*.md"))
        todo = [f for f in files if f.name not in existing]
        if not todo:
            print(f"  「{d.name}」：{len(files)} 篇文档已在库里")
            continue
        uploaded = ragflow.upload_documents(ds_id, todo)
        ragflow.parse_documents(ds_id, [doc["id"] for doc in uploaded])
        print(f"  「{d.name}」：上传 {len(uploaded)} 篇，解析中…")

        deadline = time.time() + args.timeout
        while time.time() < deadline:
            status = ragflow.document_status(ds_id)
            runs = [status.get(f.name, "") for f in todo]
            if all(r in (DONE, FAIL, "") for r in runs):
                break
            time.sleep(3)
        status = ragflow.document_status(ds_id)
        ok = sum(1 for f in todo if status.get(f.name) == DONE)
        bad = [f.name for f in todo if status.get(f.name) == FAIL]
        msg = f"  「{d.name}」：解析完成 {ok}/{len(todo)}"
        print(msg + (f"，失败：{'、'.join(bad)}（可在 RAGFlow 网页里查看原因）" if bad else ""))
    print("✓ 完成。检索端点已就绪；权限仍由中枢按岗位包过滤")


if __name__ == "__main__":
    main()
