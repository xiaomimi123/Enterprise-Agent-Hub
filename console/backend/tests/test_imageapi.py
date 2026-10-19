"""第三方出图 API（apimart 风格：提交拿任务号，再轮询取图）与出图 API 配置。"""

import dataclasses
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import imageapi, models_api, secretbox, settings_store
from app.main import app

client = TestClient(app)
KEY = "sk-image-secret-9876"


@pytest.fixture
def store(monkeypatch):
    data: dict = {}
    monkeypatch.setattr(settings_store, "get", lambda k, default=None: data.get(k, default))
    monkeypatch.setattr(settings_store, "put", lambda k, v: data.__setitem__(k, json.loads(json.dumps(v))))
    monkeypatch.setattr(secretbox, "settings", dataclasses.replace(secretbox.settings, file_secret="s3cret"))
    audits = []
    monkeypatch.setattr(models_api, "_audit", lambda user, tool, detail, result="通过": audits.append((tool, detail, result)))
    data["_audits"] = audits
    return data


def fake_apimart(polls=("running", "completed"), submit_status=200, fail=False):
    seen = {"requests": [], "polls": list(polls)}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["requests"].append((request.method, request.url.path, json.loads(request.content) if request.content else None,
                                 request.headers.get("authorization")))
        if request.url.path == "/v1/images/generations":
            if submit_status != 200:
                return httpx.Response(submit_status, json={"error": {"message": f"bad key {KEY}"}})
            return httpx.Response(200, json={"code": 200, "data": [{"status": "submitted", "task_id": "task_01"}]})
        if request.url.path == "/v1/tasks/task_01":
            state = seen["polls"].pop(0) if len(seen["polls"]) > 1 else seen["polls"][0]
            if state == "completed":
                return httpx.Response(200, json={"code": 200, "data": {"status": "completed", "result": {
                    "images": [{"url": ["https://cdn.example/a.png"]}, {"url": ["https://cdn.example/b.png"]}]}}})
            return httpx.Response(200, json={"code": 200, "data": {"status": state}})
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=b"PNGDATA")
        return httpx.Response(404)

    return seen, httpx.Client(transport=httpx.MockTransport(handler))


def client_for(http, **kw):
    return imageapi.ApimartClient("https://api.apimart.ai", KEY, "gpt-image-1", client=http, **kw)


def test_submit_sends_ratio_and_returns_task_id():
    seen, http = fake_apimart()
    task = client_for(http, params={"resolution": "1K"}).submit("一只猫", 768, 1024, 2)
    assert task == "task_01"
    method, path, body, auth = seen["requests"][0]
    assert (method, path, auth) == ("POST", "/v1/images/generations", f"Bearer {KEY}")
    assert body == {"model": "gpt-image-1", "prompt": "一只猫", "size": "3:4", "n": 2, "resolution": "1K"}


def test_poll_states_and_result_urls():
    seen, http = fake_apimart(polls=("running", "completed"))
    c = client_for(http)
    assert c.poll("task_01") == ("running", [])
    assert c.poll("task_01") == ("done", ["https://cdn.example/a.png", "https://cdn.example/b.png"])
    _, http2 = fake_apimart(polls=("failed",))
    assert client_for(http2).poll("task_01")[0] == "failed"
    assert client_for(http).download("https://cdn.example/a.png") == b"PNGDATA"


def test_errors_never_contain_the_key():
    _, http = fake_apimart(submit_status=401)
    with pytest.raises(imageapi.ImageApiError) as e:
        client_for(http).submit("x", 512, 512, 1)
    assert KEY not in str(e.value) and "401" in str(e.value)


def test_providers_store_encrypted_and_list_masks(store):
    p = imageapi.add_provider("apimart", "https://api.apimart.ai/v1", "gpt-image-1", KEY, params={"resolution": "1K"})
    assert p["key_hint"] == "••••9876" and p["base_url"] == "https://api.apimart.ai" and p["enabled"] is True
    assert KEY not in json.dumps(store) and "key" not in imageapi.list_providers()[0]
    assert imageapi.active_provider() is None                      # 还没把通道切到 API
    imageapi.set_route("api")
    active = imageapi.active_provider()
    assert active["key"] == KEY and active["model"] == "gpt-image-1" and active["params"] == {"resolution": "1K"}


def test_patch_without_key_keeps_ciphertext_and_set_route_needs_provider(store):
    with pytest.raises(imageapi.ImageApiError, match="没有可用的出图 API"):
        imageapi.set_route("api")
    p = imageapi.add_provider("apimart", "https://api.apimart.ai", "m", KEY)
    before = store["image.providers"][0]["key_enc"]
    imageapi.patch_provider(p["id"], model="m2")
    assert store["image.providers"][0]["key_enc"] == before and imageapi.list_providers()[0]["model"] == "m2"
    imageapi.patch_provider(p["id"], key="sk-new-0000")
    assert store["image.providers"][0]["key_enc"] != before and imageapi.list_providers()[0]["key_hint"] == "••••0000"
    imageapi.set_route("api")
    imageapi.patch_provider(p["id"], enabled=False)
    assert imageapi.get_route() == "gpu"                           # 唯一的出图 API 被停用时通道自动退回本机 GPU
    imageapi.remove_provider(p["id"])
    assert imageapi.list_providers() == []


def test_routes_validate_and_audit_without_key(store):
    r = client.post("/api/models/image/providers", json={"name": "apimart", "base_url": "https://api.apimart.ai", "model": "m", "key": KEY})
    assert r.status_code == 200 and r.json()["key_hint"] == "••••9876" and KEY not in r.text
    pid = r.json()["id"]
    assert client.put("/api/models/image/route", json={"route": "api"}).json()["route"] == "api"
    assert client.put("/api/models/image/route", json={"route": "bogus"}).status_code == 400
    cfg = client.get("/api/models/image").json()
    assert cfg["route"] == "api" and cfg["providers"][0]["id"] == pid and KEY not in json.dumps(cfg)
    assert client.post("/api/models/image/providers", json={"name": "", "base_url": "https://a", "model": "m", "key": KEY}).status_code == 400
    assert client.delete(f"/api/models/image/providers/{pid}").status_code == 200
    assert client.get("/api/models/image").json()["route"] == "gpu"
    assert all(KEY not in " ".join(a) for a in store["_audits"]) and len(store["_audits"]) == 3


def test_provider_test_endpoint_reports_result_without_key(store, monkeypatch):
    p = imageapi.add_provider("apimart", "https://api.apimart.ai", "m", KEY)
    monkeypatch.setattr(imageapi.ApimartClient, "test", lambda self: {"ok": False, "seconds": 1.2, "error": f"401 {KEY}"})
    r = client.post(f"/api/models/image/providers/{p['id']}/test")
    assert r.status_code == 200 and r.json()["ok"] is False and KEY not in r.text
