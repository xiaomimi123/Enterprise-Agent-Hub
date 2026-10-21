"""把 vault（Obsidian）里的知识库文档同步到 RAGFlow，可重复执行。

vault/<知识库名>/**/*.md → 数据集 hub-<kb_id> 里的文档（文档名 = 文件名）。
按「文件名 + 字节数」判断是否变化：没变就跳过，变了先删旧文档再上传新的，本地删除的文件同步删除。
"""

from __future__ import annotations

import time
from pathlib import Path

from .config import settings
from .content import DATASET_PREFIX, KB_BY_NAME, KB_REGISTRY
from .ragflow import Ragflow


def sync_vault(client: Ragflow, vault_dir: str, wait: bool = False, timeout: float = 600) -> dict:
    stats = {"uploaded": 0, "updated": 0, "deleted": 0, "skipped": 0}
    parse_jobs: list[tuple[str, list[str]]] = []
    for folder in sorted(Path(vault_dir).iterdir()):
        kb_id = KB_BY_NAME.get(folder.name) if folder.is_dir() else None
        if not kb_id:
            continue
        ds = client.ensure_dataset(f"{DATASET_PREFIX}{kb_id}", KB_REGISTRY[kb_id]["name"], settings.ragflow_embedding_model)
        remote = {d["name"]: d for d in client.list_documents(ds)}
        local = {p.name: p for p in sorted(folder.rglob("*.md"))}

        gone = [d["id"] for name, d in remote.items() if name not in local]
        stale = {name for name, p in local.items() if name in remote and int(remote[name].get("size") or -1) != p.stat().st_size}
        if gone or stale:
            client.delete_documents(ds, gone + [remote[n]["id"] for n in stale])
        stats["deleted"] += len(gone)

        new_ids = []
        for name, p in local.items():
            if name in remote and name not in stale:
                stats["skipped"] += 1
                continue
            new_ids.append(client.upload(ds, name, p.read_bytes()))
            stats["updated" if name in stale else "uploaded"] += 1
        if new_ids:
            client.parse(ds, new_ids)
            parse_jobs.append((ds, new_ids))
    if wait:
        _wait_parsed(client, parse_jobs, timeout)
    return stats


def sync_db(client: Ragflow, wait: bool = False, timeout: float = 600) -> dict:
    """把数据库里当前生效的知识库文档同步到 RAGFlow（控制台编辑后的内容以数据库为准），按「文件名 + 字节数」判断变化。"""
    from . import db, kbstore
    stats = {"uploaded": 0, "updated": 0, "deleted": 0, "skipped": 0}
    parse_jobs: list[tuple[str, list[str]]] = []
    docs = kbstore.published_docs()
    for kb_id, meta in KB_REGISTRY.items():
        local = {f"{d['name']}{kbstore.EXTENSION}": d["content"].encode("utf-8") for d in docs if d["kb_id"] == kb_id}
        ds = client.ensure_dataset(f"{DATASET_PREFIX}{kb_id}", meta["name"], settings.ragflow_embedding_model)
        remote = {d["name"]: d for d in client.list_documents(ds)}
        gone = [d["id"] for name, d in remote.items() if name not in local]
        stale = {name for name, data in local.items() if name in remote and int(remote[name].get("size") or -1) != len(data)}
        if gone or stale:
            client.delete_documents(ds, gone + [remote[n]["id"] for n in stale])
        stats["deleted"] += len(gone)
        new_ids = []
        for name, data in local.items():
            if name in remote and name not in stale:
                stats["skipped"] += 1
                continue
            new_ids.append(client.upload(ds, name, data))
            stats["updated" if name in stale else "uploaded"] += 1
        if new_ids:
            client.parse(ds, new_ids)
            parse_jobs.append((ds, new_ids))
    with db.connect() as conn:
        conn.execute("UPDATE kb_docs SET synced_version = published_version WHERE published_version > 0")
    if wait:
        _wait_parsed(client, parse_jobs, timeout)
    return stats


def _wait_parsed(client: Ragflow, jobs: list[tuple[str, list[str]]], timeout: float) -> None:
    deadline = time.time() + timeout
    for ds, ids in jobs:
        while time.time() < deadline:
            runs = {d["id"]: d.get("run") for d in client.list_documents(ds) if d["id"] in ids}
            if all(r in ("DONE", "FAIL") for r in runs.values()):
                break
            time.sleep(3)
