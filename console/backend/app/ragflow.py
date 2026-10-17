"""RAGFlow 客户端：知识库的向量 + 关键词混合检索，以及把 vault 文档同步成数据集。

一个知识库对应 RAGFlow 里的一个数据集（名称 hub-<kb_id>）。权限不在这里判断：调用方先按岗位包算出
能查哪些知识库，再只把这些库的数据集 ID 传进来。RAGFlow 的 REST 接口见其 docs/references/http_api_reference.md。
"""

from __future__ import annotations

import httpx

from .config import settings


class RagflowError(RuntimeError):
    pass


class Ragflow:
    def __init__(self, endpoint: str, api_key: str, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=endpoint.rstrip("/"), headers={"Authorization": f"Bearer {api_key}"},
                                 timeout=30, transport=transport)

    def _call(self, method: str, path: str, **kw) -> object:
        try:
            r = self.http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise RagflowError(f"RAGFlow 不可达：{e}") from e
        if r.status_code >= 400:
            raise RagflowError(f"RAGFlow {path} 返回 HTTP {r.status_code}")
        body = r.json()
        if body.get("code") != 0:
            raise RagflowError(f"RAGFlow {path} 失败：{body.get('message')}")
        return body.get("data")

    # ---- 数据集 ----
    def find_dataset(self, name: str) -> str | None:
        rows = self._call("GET", "/api/v1/datasets", params={"name": name, "page_size": 100}) or []
        return next((d["id"] for d in rows if d.get("name") == name), None)

    def ensure_dataset(self, name: str, description: str = "") -> str:
        found = self.find_dataset(name)
        if found:
            return found
        return self._call("POST", "/api/v1/datasets", json={"name": name, "description": description})["id"]

    # ---- 文档 ----
    def list_documents(self, dataset_id: str) -> list[dict]:
        out, page = [], 1
        while True:
            data = self._call("GET", f"/api/v1/datasets/{dataset_id}/documents", params={"page": page, "page_size": 100}) or {}
            docs = data.get("docs", [])
            out += docs
            if len(docs) < 100:
                return out
            page += 1

    def upload(self, dataset_id: str, filename: str, data: bytes) -> str:
        rows = self._call("POST", f"/api/v1/datasets/{dataset_id}/documents", files={"file": (filename, data, "text/markdown")})
        return rows[0]["id"]

    def delete_documents(self, dataset_id: str, ids: list[str]) -> None:
        self._call("DELETE", f"/api/v1/datasets/{dataset_id}/documents", json={"ids": ids})

    def parse(self, dataset_id: str, doc_ids: list[str]) -> None:
        self._call("POST", f"/api/v1/datasets/{dataset_id}/chunks", json={"document_ids": doc_ids})

    # ---- 检索 ----
    def retrieve(self, question: str, dataset_ids: list[str], top_k: int = 5) -> list[dict]:
        data = self._call("POST", "/api/v1/retrieval",
                          json={"question": question, "dataset_ids": dataset_ids, "page_size": top_k}) or {}
        return data.get("chunks", [])


def from_settings() -> Ragflow | None:
    """配置了地址和密钥才启用；否则返回 None，调用方回退到本地检索。"""
    if not settings.ragflow_endpoint or not settings.ragflow_api_key:
        return None
    return Ragflow(settings.ragflow_endpoint, settings.ragflow_api_key)
