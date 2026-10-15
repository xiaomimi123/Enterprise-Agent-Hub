"""RAGFlow 检索接入：dataset 解析、命中结构映射、错误回退本地检索、未配置时走本地。"""
import dataclasses
import json

import httpx

from app import content, ragflow

HITS = [{"knowledge_base": "财务制度与报表", "kb_id": "ds-1", "document": "报销制度.md",
         "section": "", "text": "报销需在 30 日内提交", "score": 0.834}]


def setup_function():
    ragflow._HTTP = None
    ragflow._datasets_cache = (0.0, {})


def install(monkeypatch, handler, endpoint="http://rag", key="rk-1"):
    monkeypatch.setattr(ragflow, "settings",
                        dataclasses.replace(ragflow.settings, ragflow_endpoint=endpoint, ragflow_api_key=key))
    monkeypatch.setattr(ragflow, "_HTTP", httpx.Client(transport=httpx.MockTransport(handler),
                                                       base_url=endpoint,
                                                       headers={"Authorization": f"Bearer {key}"}))


def ragflow_up(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/datasets":
        return httpx.Response(200, json={"code": 0, "data": [{"name": "财务制度与报表", "id": "ds-1"}]})
    if request.url.path == "/api/v1/retrieval":
        body = json.loads(request.content)
        assert body["dataset_ids"] == ["ds-1"] and body["question"] == "报销期限"
        return httpx.Response(200, json={"code": 0, "data": {"total": 1, "chunks": [{
            "content": "报销需在 30 日内提交", "document_keyword": "报销制度.md",
            "dataset_id": "ds-1", "similarity": 0.834}]}})
    return httpx.Response(404, json={"code": 100})


def test_search_maps_hits(monkeypatch):
    install(monkeypatch, ragflow_up)
    hits = ragflow.search("报销期限", ["财务制度与报表"])
    assert hits == HITS


def test_unknown_dataset_returns_empty(monkeypatch):
    install(monkeypatch, ragflow_up)
    assert ragflow.search("报销期限", ["没建过的库"]) == []


def test_upstream_error_raises(monkeypatch):
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 100, "message": "unauthorized"})

    install(monkeypatch, broken)
    try:
        ragflow.search("x", ["财务制度与报表"])
        assert False, "应当抛错"
    except ragflow.RagFlowError:
        pass


def test_content_search_prefers_ragflow(monkeypatch):
    install(monkeypatch, ragflow_up)
    monkeypatch.setattr(content, "settings",
                        dataclasses.replace(content.settings, ragflow_endpoint="http://rag", ragflow_api_key="rk-1"))
    hits = content.search("报销期限", ["kb-finance"])
    assert hits == HITS  # RAGFlow 命中结构原样返回，权限过滤由调用方完成


def test_content_search_falls_back_on_error(monkeypatch):
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    install(monkeypatch, broken)
    monkeypatch.setattr(content, "settings",
                        dataclasses.replace(content.settings, ragflow_endpoint="http://rag", ragflow_api_key="rk-1"))
    hits = content.search("报销", ["kb-finance"])
    assert hits and all(h["knowledge_base"] == "财务制度与报表" for h in hits)  # 回退本地 vault 检索


def test_content_search_local_when_unconfigured(monkeypatch):
    monkeypatch.setattr(content, "settings",
                        dataclasses.replace(content.settings, ragflow_endpoint="", ragflow_api_key=""))
    hits = content.search("报销", ["kb-finance"])
    assert hits and all(h["kb_id"] == "kb-finance" for h in hits)
