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
