import json

import httpx
import pytest

from app import ragflow
from app.ragflow import Ragflow, RagflowError


def make(handler) -> tuple[Ragflow, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    return Ragflow("http://rf:9380", "key-1", transport=httpx.MockTransport(wrapped)), seen


def ok(data=None) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "data": data})


def test_requests_carry_bearer_key():
    rf, seen = make(lambda r: ok([]))
    rf.find_dataset("hub-kb-brand")
    assert seen[0].headers["Authorization"] == "Bearer key-1"


def test_ensure_dataset_reuses_existing_and_creates_missing():
    def handler(req):
        if req.method == "GET":
            return ok([{"id": "ds-1", "name": "hub-kb-brand"}])
        return ok({"id": "ds-new", "name": json.loads(req.content)["name"]})

    rf, seen = make(handler)
    assert rf.ensure_dataset("hub-kb-brand") == "ds-1"
    assert [r.method for r in seen] == ["GET"]  # 已存在：不创建

    rf, seen = make(handler)
    assert rf.ensure_dataset("hub-kb-hr", "人事") == "ds-new"
    post = next(r for r in seen if r.method == "POST")
    assert post.url.path == "/api/v1/datasets" and json.loads(post.content)["name"] == "hub-kb-hr"


def test_retrieve_sends_scope_and_page_size():
    rf, seen = make(lambda r: ok({"chunks": [{"content": "c", "dataset_id": "ds-1"}], "total": 1}))
    chunks = rf.retrieve("保湿", ["ds-1", "ds-2"], top_k=3)
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/api/v1/retrieval"
    assert body["question"] == "保湿" and body["dataset_ids"] == ["ds-1", "ds-2"] and body["page_size"] == 3
    assert chunks == [{"content": "c", "dataset_id": "ds-1"}]


def test_error_code_raises_with_message():
    rf, _ = make(lambda r: httpx.Response(200, json={"code": 102, "message": "`dataset_ids` is required."}))
    with pytest.raises(RagflowError, match="dataset_ids"):
        rf.retrieve("x", [])


def test_http_failure_raises():
    rf, _ = make(lambda r: httpx.Response(502, text="bad gateway"))
    with pytest.raises(RagflowError):
        rf.find_dataset("a")


def test_from_settings_requires_endpoint_and_key(monkeypatch):
    import dataclasses
    for endpoint, key, expect in (("", "k", False), ("http://rf", "", False), ("http://rf", "k", True)):
        monkeypatch.setattr(ragflow, "settings", dataclasses.replace(ragflow.settings, ragflow_endpoint=endpoint, ragflow_api_key=key))
        assert (ragflow.from_settings() is not None) is expect


# ---- content.search 切换到 RAGFlow ----

from app import content  # noqa: E402


class FakeRagflow:
    def __init__(self, datasets: dict[str, str], chunks=None, error: Exception | None = None):
        self.datasets, self.chunks, self.error, self.retrieved = datasets, chunks or [], error, []

    def find_dataset(self, name):
        return self.datasets.get(name)

    def retrieve(self, question, dataset_ids, top_k=5):
        self.retrieved.append((question, list(dataset_ids), top_k))
        if self.error:
            raise self.error
        return self.chunks


def use(monkeypatch, fake):
    monkeypatch.setattr(content, "from_settings", lambda: fake)


def test_search_maps_chunks_and_scopes_datasets(monkeypatch):
    fake = FakeRagflow({"hub-kb-brand": "ds-brand", "hub-kb-finance": "ds-fin"}, chunks=[
        {"content": "秋冬主张：温暖", "dataset_id": "ds-brand", "document_keyword": "2026秋冬品牌主张.md", "similarity": 0.8123456},
    ])
    use(monkeypatch, fake)
    hits = content.search("品牌主张", ["kb-brand"])
    assert fake.retrieved == [("品牌主张", ["ds-brand"], 5)]  # 只查有权限的库，不含财务
    assert hits == [{"knowledge_base": "品牌调性与人设", "kb_id": "kb-brand", "document": "2026秋冬品牌主张",
                     "section": "", "text": "秋冬主张：温暖", "score": 0.812}]


def test_search_skips_empty_inputs(monkeypatch):
    fake = FakeRagflow({"hub-kb-brand": "ds-brand"})
    use(monkeypatch, fake)
    assert content.search("品牌", []) == []
    assert content.search("   ", ["kb-brand"]) == []
    assert fake.retrieved == []


def test_search_skips_kb_without_dataset(monkeypatch):
    fake = FakeRagflow({"hub-kb-brand": "ds-brand"})
    use(monkeypatch, fake)
    content.search("x", ["kb-brand", "kb-hr"])  # kb-hr 还没同步：跳过，不扩大范围
    assert fake.retrieved[0][1] == ["ds-brand"]
    fake.retrieved.clear()
    assert content.search("x", ["kb-hr"]) == [] and fake.retrieved == []


def test_search_falls_back_to_local_on_error(monkeypatch):
    use(monkeypatch, FakeRagflow({"hub-kb-product": "ds-p"}, error=RagflowError("down")))
    hits = content.search("保湿精华", ["kb-product"])
    assert hits and all(h["kb_id"] == "kb-product" for h in hits)  # 本地 vault 的结果


def test_search_uses_local_when_not_configured(monkeypatch):
    use(monkeypatch, None)
    assert content.search("保湿精华", ["kb-product"]) == content.local_search("保湿精华", ["kb-product"])
