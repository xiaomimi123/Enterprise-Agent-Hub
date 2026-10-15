"""模型代理（/v1）：key 识别员工、转发与流式透传、token 记入审计、错误透传。"""
import dataclasses
import json

import httpx
from fastapi.testclient import TestClient

from app import db, model_proxy
from app.main import app

client = TestClient(app)

OWNER = {"key_hash": "h", "org": "xinghe", "user_name": "u1", "display_name": "林小运",
         "dept": "运营部", "channel": "官方 agent"}
AUDITS: list[dict] = []
UPSTREAM: list[httpx.Request] = []


def setup_function():
    AUDITS.clear()
    UPSTREAM.clear()


def install(monkeypatch, handler, owner_key="sk-known"):
    """把上游换成内存假实现，把数据库换成字典假实现。"""
    monkeypatch.setattr(model_proxy, "settings",
                        dataclasses.replace(model_proxy.settings, newapi_endpoint="http://upstream"))
    monkeypatch.setattr(model_proxy, "_HTTP", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(db, "model_key_owner", lambda key: dict(OWNER) if key == owner_key else None)
    monkeypatch.setattr(db, "add_audit", lambda **e: AUDITS.append(e))


def post(payload, headers=None):
    h = {"Authorization": "Bearer sk-known", **(headers or {})}
    return client.post("/v1/chat/completions", json=payload, headers=h)


def test_unknown_key_rejected_without_forwarding(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json={}), owner_key="sk-other")
    r = post({})
    assert r.status_code == 401 and "重新同步" in r.json()["error"]["message"]
    assert not UPSTREAM and not AUDITS


def test_non_stream_forwarded_and_audited(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        UPSTREAM.append(request)
        return httpx.Response(200, json={"id": "c1", "model": "hub-mock",
                                         "usage": {"prompt_tokens": 11, "completion_tokens": 7}})

    install(monkeypatch, handler)
    r = post({"model": "hub-mock", "messages": [{"role": "user", "content": "帮我写一篇保湿精华的种草笔记"}]},
             headers={"X-Hub-Trace-Id": "chat-abc123"})
    assert r.status_code == 200 and r.json()["usage"]["prompt_tokens"] == 11
    assert UPSTREAM[0].url.host == "upstream" and UPSTREAM[0].headers["Authorization"] == "Bearer sk-known"
    a = AUDITS[0]
    assert a["trace_id"] == "chat-abc123" and a["kind"] == "模型" and a["tool"] == "model.chat"
    assert a["org"] == "xinghe" and a["user_name"] == "u1" and a["display_name"] == "林小运"
    assert a["tokens"] == 18 and a["model"] == "hub-mock" and a["result"] == "通过"
    assert "帮我写一篇保湿精华的种草笔记" in a["detail"]


def test_stream_passthrough_with_usage_from_final_chunk(monkeypatch):
    sse = ('data: {"model":"hub-mock","choices":[{"delta":{"content":"好"}}]}\n\n'
           'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":20}}\n\n'
           'data: [DONE]\n\n')

    def handler(request: httpx.Request) -> httpx.Response:
        UPSTREAM.append(request)
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

    install(monkeypatch, handler)
    r = post({"model": "hub-mock", "stream": True, "messages": [{"role": "user", "content": "在吗"}]})
    assert r.status_code == 200 and r.text == sse  # 字节原样透传
    a = AUDITS[0]
    assert a["tokens"] == 120 and a["model"] == "hub-mock" and a["result"] == "通过"
    assert a["trace_id"].startswith("llm-")  # 没带追踪头：单独成条，不丢审计


def test_upstream_denial_passed_through_and_audited(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        UPSTREAM.append(request)
        return httpx.Response(429, json={"error": {"message": "额度已用尽，请联系管理员"}})

    install(monkeypatch, handler)
    r = post({"model": "hub-mock", "messages": [{"role": "user", "content": "hi"}]},
             headers={"X-Hub-Trace-Id": "chat-abc123"})
    assert r.status_code == 429
    a = AUDITS[0]
    assert a["result"] == "拒绝" and a["tokens"] == 0 and a["trace_id"] == "chat-abc123"
    assert "额度已用尽" in a["detail"]


def test_gateway_down_audited_as_denial(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    install(monkeypatch, handler)
    r = post({"model": "hub-mock", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 502 and AUDITS[0]["result"] == "拒绝"
