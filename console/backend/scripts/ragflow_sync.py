"""把 vault 里的知识库同步到 RAGFlow。

用法：uv run python scripts/ragflow_sync.py [--wait]
需要环境变量 RAGFLOW_ENDPOINT、RAGFLOW_API_KEY（容器里已配置；本机运行时在 console/backend/.env 里设置）。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import kb_sync, ragflow  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", action="store_true", help="等待 RAGFlow 解析完成")
    args = ap.parse_args()
    client = ragflow.from_settings()
    if client is None:
        sys.exit("未配置 RAGFLOW_ENDPOINT / RAGFLOW_API_KEY")
    stats = kb_sync.sync_vault(client, settings.vault_dir, wait=args.wait)
    print(f"同步完成：新增 {stats['uploaded']}，更新 {stats['updated']}，删除 {stats['deleted']}，未变 {stats['skipped']}")


if __name__ == "__main__":
    main()
