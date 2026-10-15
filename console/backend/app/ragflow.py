"""RAGFlow 知识库检索客户端（对 RAGFlow v0.27 的 HTTP API）。

知识库在 RAGFlow 里是一个个 dataset，名字与 vault/ 下的文件夹名一致（scripts/ragflow_bootstrap.py
负责建库、传文档、触发解析）。运行时只做一件事：检索。

- 公开接口都用 Authorization: Bearer <API key>（GET/POST /api/v1/...，见 RAGFlow docs/references/http_api_reference.md）
- search() 返回与本地检索相同的命中结构，content.search() 据此无缝切换
- RAGFlow 出错时抛 RagFlowError，由调用方决定回退本地检索；「检索到 0 条」是正常结果，不回退
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from .config import settings

log = logging.getLogger("hub.ragflow")

_TIMEOUT = httpx.Timeout(connect=10, read=60, write=60, pool=60)
_HTTP: httpx.Client | None = None
# dataset 名 → id 的解析结果缓存（RAGFlow 里建库不频繁）
_datasets_cache: tuple[float, dict[str, str]] = (0.0, [])


class RagFlowError(RuntimeError):
    pass


def configured() -> bool:
    return bool(settings.ragflow_endpoint and settings.ragflow_api_key)


def _client() -> httpx.Client:
    global _HTTP
    if _HTTP is None:
        _HTTP = httpx.Client(base_url=settings.ragflow_endpoint, timeout=_TIMEOUT,
                             headers={"Authorization": f"Bearer {settings.ragflow_api_key}"})
    return _HTTP


def _check(body: dict, what: str) -> dict:
    if body.get("code") != 0:
        raise RagFlowError(f"RAGFlow {what} 失败：{body.get('message')}")
    return body.get("data") or {}


def datasets() -> dict[str, str]:
    """全部 dataset：名字 → id（缓存 5 分钟）。"""
    global _datasets_cache
    if time.time() - _datasets_cache[0] < 300:
        return dict(_datasets_cache[1])
    out: dict[str, str] = {}
    page = 1
    while True:
        data = _check(_client().get("/api/v1/datasets", params={"page": page, "page_size": 100}).json(),
                      "读取 dataset 列表")
        items = data if isinstance(data, list) else []
        for d in items:
            out[d["name"]] = d["id"]
        if len(items) < 100:
            break
        page += 1
    _datasets_cache = (time.time(), dict(out))
    return out


def search(query: str, kb_names: list[str], top_k: int = 5) -> list[dict]:
    """在指定知识库（dataset 名单）中检索，返回与本地检索相同的命中结构。

    调用方（content.search）已按权限过滤知识库，这里只会拿到允许的 dataset id。
    """
    if not kb_names:
        return []
    ids = datasets()
    dataset_ids = [ids[n] for n in kb_names if n in ids]
    if not dataset_ids:
        log.warning("RAGFlow 里找不到这些知识库（还没 bootstrap？）：%s", "、".join(kb_names))
        return []
    data = _check(_client().post("/api/v1/retrieval", json={
        "question": query, "dataset_ids": dataset_ids, "page_size": top_k,
        "similarity_threshold": 0.2,
    }).json(), "检索")
    id_name = {v: k for k, v in ids.items()}
    out = []
    for c in data.get("chunks", []):
        kb_name = id_name.get(c.get("dataset_id"), "")
        out.append({
            "knowledge_base": kb_name, "kb_id": c.get("dataset_id"),
            "document": c.get("document_keyword") or "",
            "section": "、".join(c.get("important_keywords") or [])[:40],
            "text": (c.get("content") or "").strip(),
            "score": round(float(c.get("similarity") or 0), 3),
        })
    return out[:top_k]


# ---- bootstrap 用：建库、传文档、触发解析、看进度（scripts/ragflow_bootstrap.py 调用）----

def create_dataset(name: str) -> str:
    """建 dataset（已存在则返回现有 id）。embedding 用 RAGFlow 内置的 bge 中文模型（离线可用）。"""
    ids = datasets()
    if name in ids:
        return ids[name]
    data = _check(_client().post("/api/v1/datasets", json={
        "name": name, "chunk_method": "naive",
        "embedding_model": "BAAI/bge-large-zh-v1.5@BAAI",
    }).json(), f"创建知识库「{name}」")
    global _datasets_cache
    _datasets_cache = (0.0, {})
    return data["id"]


def _list_documents(dataset_id: str) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        data = _check(_client().get(f"/api/v1/datasets/{dataset_id}/documents",
                                    params={"page": page, "page_size": 100}).json(), "读取文档列表")
        page_items = data.get("docs", []) if isinstance(data, dict) else (data or [])
        items += page_items
        if len(page_items) < 100:
            break
        page += 1
    return items


def documents(dataset_id: str) -> dict[str, str]:
    """dataset 里已有的文档：文件名 → id。"""
    return {d["name"]: d["id"] for d in _list_documents(dataset_id)}


def upload_documents(dataset_id: str, files: list[Path]) -> list[dict]:
    """上传文档（multipart，字段名 file），返回 RAGFlow 的文档记录。"""
    out = []
    for batch in (files[i:i + 5] for i in range(0, len(files), 5)):
        payload = [("file", (f.name, f.read_bytes())) for f in batch]
        data = _check(_client().post(f"/api/v1/datasets/{dataset_id}/documents",
                                     files=payload).json(), "上传文档")
        out += data if isinstance(data, list) else data.get("documents", [])
    return out


def parse_documents(dataset_id: str, doc_ids: list[str]) -> None:
    """触发解析（v0.27：POST /datasets/{id}/chunks）。"""
    _check(_client().post(f"/api/v1/datasets/{dataset_id}/chunks",
                          json={"document_ids": doc_ids}).json(), "触发解析")


def document_status(dataset_id: str) -> dict[str, str]:
    """文档名 → 解析状态（0 未开始 / 1 进行中 / 3 完成 / 4 失败 / 5 排队）。"""
    return {d["name"]: str(d.get("run", "")) for d in _list_documents(dataset_id)}
