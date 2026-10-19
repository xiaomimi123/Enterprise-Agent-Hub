"""对话模型上游：控制台读写 New API 渠道；密钥只写不读，页面只显示后四位。"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import model_upstreams, models_api, newapi
from app.main import app

client = TestClient(app)
KEY = "sk-secret-abcd1234"


class FakeGateway:
    """假的 New API 管理接口：记录收到的请求，渠道列表里的 key 永远是空串（和真实行为一致）。"""

    def __init__(self):
        self.channels = [{"id": 1, "name": "hub-mock", "type": 1, "status": 1, "base_url": "http://mock-llm:8300",
                          "models": "hub-mock", "remark": None, "key": ""}]
        self.requests = []
        self.fail_models = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.method, request.url.path, body))
        ok = lambda data=None: httpx.Response(200, json={"success": True, "message": "", "data": data})  # noqa: E731
        path = request.url.path
        if path == "/api/channel/" and request.method == "GET":
            return ok({"items": self.channels})
        if path == "/api/channel/fetch_models":
            if self.fail_models:
                return httpx.Response(200, json={"success": False, "message": self.fail_models})
            return ok(["m-a", "m-b"])
        if path == "/api/channel/" and request.method == "POST":
            c = body["channel"]
            self.channels.append({"id": 10 + len(self.channels), "key": "", **{k: c[k] for k in ("name", "type", "status", "base_url", "models")},
                                  "remark": c.get("remark")})
            return ok()
        if path == "/api/channel/" and request.method == "PUT":
            c = next(c for c in self.channels if c["id"] == body["id"])
            c.update({k: v for k, v in body.items() if k != "key"})
            return ok(c)
        if request.method == "DELETE":
            self.channels = [c for c in self.channels if f"/api/channel/{c['id']}" != path]
            return ok()
        return httpx.Response(404, json={"success": False, "message": "?"})


@pytest.fixture
def gw(monkeypatch):
    g = FakeGateway()

    def make():
        na = newapi.NewApi("http://gw", "tok", "1")
        na.http = httpx.Client(base_url="http://gw", transport=httpx.MockTransport(g.handler))
        return na
    monkeypatch.setattr(models_api, "make_newapi", make)
    audits = []
    monkeypatch.setattr(models_api, "_audit", lambda user, tool, detail, result="通过": audits.append((tool, detail, result)))
    g.audits = audits
    return g


def test_list_shows_channels_without_keys(gw):
    [u] = client.get("/api/models/upstreams").json()
    assert u == {"id": 1, "name": "hub-mock", "base_url": "http://mock-llm:8300", "models": ["hub-mock"],
                 "status": "enabled", "key_hint": ""}


def test_probe_returns_models_and_errors_never_echo_key(gw):
    ok = client.post("/api/models/upstreams/probe", json={"base_url": "https://api.x.com/v1", "key": KEY})
    assert ok.status_code == 200 and ok.json() == {"models": ["m-a", "m-b"]}
    sent = [b for m, p, b in gw.requests if p.endswith("fetch_models")][0]
    assert sent["base_url"] == "https://api.x.com"                       # 末尾的 /v1 去掉：New API 自己会拼 /v1/...
    gw.fail_models = f"auth failed for {KEY}"
    bad = client.post("/api/models/upstreams/probe", json={"base_url": "https://api.x.com", "key": KEY})
    assert bad.status_code == 400 and KEY not in bad.text


def test_add_creates_channel_with_hint_and_audits_without_key(gw):
    r = client.post("/api/models/upstreams", json={"name": "中转平台", "base_url": "https://relay.example/v1/", "key": KEY,
                                                    "models": ["m-a"]})
    assert r.status_code == 200 and r.json()["key_hint"] == "••••1234" and r.json()["models"] == ["m-a"]
    created = [b for m, p, b in gw.requests if m == "POST" and p == "/api/channel/"][0]["channel"]
    assert created["key"] == KEY and created["base_url"] == "https://relay.example" and created["type"] == 1
    assert created["models"] == "m-a" and created["remark"] == "••••1234"
    assert gw.audits and all(KEY not in " ".join(a) for a in gw.audits) and "中转平台" in gw.audits[-1][1]


@pytest.mark.parametrize("body,msg", [
    ({"name": "x", "base_url": "ftp://a", "key": KEY, "models": ["m"]}, "地址"),
    ({"name": "", "base_url": "https://a.com", "key": KEY, "models": ["m"]}, "名称"),
    ({"name": "x", "base_url": "https://a.com", "key": "", "models": ["m"]}, "密钥"),
    ({"name": "x", "base_url": "https://a.com", "key": KEY, "models": []}, "模型"),
    ({"name": "hub-mock", "base_url": "https://a.com", "key": KEY, "models": ["m"]}, "重名"),
])
def test_add_validation(gw, body, msg):
    r = client.post("/api/models/upstreams", json=body)
    assert r.status_code == 400 and msg in r.json()["detail"]


def test_patch_without_key_does_not_send_key_and_toggles_status(gw):
    r = client.patch("/api/models/upstreams/1", json={"enabled": False, "models": ["hub-mock", "x"]})
    assert r.status_code == 200 and r.json()["status"] == "disabled" and r.json()["models"] == ["hub-mock", "x"]
    put = [b for m, p, b in gw.requests if m == "PUT"][0]
    assert "key" not in put and put["status"] == 2
    client.patch("/api/models/upstreams/1", json={"key": KEY})
    put2 = [b for m, p, b in gw.requests if m == "PUT"][-1]
    assert put2["key"] == KEY and put2["remark"] == "••••1234"
    assert all(KEY not in " ".join(a) for a in gw.audits)


def test_delete_and_missing(gw):
    assert client.delete("/api/models/upstreams/1").status_code == 200 and gw.channels == []
    assert client.patch("/api/models/upstreams/99", json={"enabled": True}).status_code == 404


def test_gateway_not_configured_is_503(monkeypatch):
    monkeypatch.setattr(models_api, "make_newapi", lambda: newapi.NewApi("", "", ""))
    r = client.get("/api/models/upstreams")
    assert r.status_code == 503 and "模型网关" in r.json()["detail"]


def test_catalog_models_come_from_enabled_upstreams(gw, monkeypatch):
    monkeypatch.setattr(newapi.NewApi, "available_models", lambda self: ["hub-mock", "m-a"])
    models = client.get("/api/catalog").json()["models"]
    assert [m["id"] for m in models] == ["hub-mock", "m-a"]


def test_catalog_keeps_demo_models_when_gateway_unavailable(monkeypatch):
    monkeypatch.setattr(models_api, "make_newapi", lambda: newapi.NewApi("", "", ""))
    assert "claude-sonnet" in [m["id"] for m in client.get("/api/catalog").json()["models"]]
