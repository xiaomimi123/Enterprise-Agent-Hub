"""模型价格：读写 New API 的 ModelRatio / CompletionRatio，页面以「美元 / 百万 token」展示和编辑。"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import models_api, newapi
from app.main import app

client = TestClient(app)


class FakePricingGateway:
    """假的 New API：选项以 JSON 字符串存放，和真实行为一致；渠道里有三个模型。"""

    def __init__(self):
        self.options = {"ModelRatio": json.dumps({"deepseek-chat": 0.135, "other-model": 1.5}),
                        "CompletionRatio": json.dumps({"deepseek-chat": 4}), "GroupRatio": "{}"}
        self.puts: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        ok = lambda data=None: httpx.Response(200, json={"success": True, "message": "", "data": data})  # noqa: E731
        path, body = request.url.path, (json.loads(request.content) if request.content else {})
        if path == "/api/option/" and request.method == "GET":
            return ok([{"key": k, "value": v} for k, v in self.options.items()])
        if path == "/api/option/" and request.method == "PUT":
            self.options[body["key"]] = body["value"]
            self.puts.append((body["key"], json.loads(body["value"])))
            return ok()
        if path == "/api/channel/":
            return ok({"items": [{"id": 1, "status": 1, "models": "deepseek-chat,deepseek-v4-flash"},
                                 {"id": 2, "status": 2, "models": "disabled-model"}]})
        return httpx.Response(404, json={"success": False, "message": "?"})


@pytest.fixture
def gw(monkeypatch):
    g = FakePricingGateway()

    def make():
        na = newapi.NewApi("http://gw", "tok", "1")
        na.http = httpx.Client(base_url="http://gw", transport=httpx.MockTransport(g.handler))
        return na
    monkeypatch.setattr(models_api, "make_newapi", make)
    audits = []
    monkeypatch.setattr(models_api, "_audit", lambda user, tool, detail, result="通过": audits.append((tool, detail)))
    g.audits = audits
    return g


def test_get_pricing_converts_ratio_to_usd_per_million_and_flags_unset_models(gw):
    r = client.get("/api/models/pricing")
    assert r.status_code == 200
    rows = {m["model"]: m for m in r.json()["models"]}
    assert set(rows) == {"deepseek-chat", "deepseek-v4-flash"}                       # 只列已启用渠道的模型
    chat = rows["deepseek-chat"]
    assert chat["configured"] and chat["input_per_m"] == 0.27 and chat["output_per_m"] == 1.08   # 0.135×2，输出再乘 4
    flash = rows["deepseek-v4-flash"]
    assert not flash["configured"] and flash["input_per_m"] == 75.0                  # 没设置：按默认 37.5 倍率，虚高
    assert r.json()["default_input_per_m"] == 75.0


def test_set_pricing_writes_ratio_and_completion_and_keeps_other_models(gw):
    r = client.put("/api/models/pricing/deepseek-v4-flash", json={"input_per_m": 0.14, "output_per_m": 0.28})
    assert r.status_code == 200 and r.json()["configured"] and r.json()["input_per_m"] == 0.14 and r.json()["output_per_m"] == 0.28
    ratios, completions = json.loads(gw.options["ModelRatio"]), json.loads(gw.options["CompletionRatio"])
    assert ratios["deepseek-v4-flash"] == 0.07 and completions["deepseek-v4-flash"] == 2.0
    assert ratios["deepseek-chat"] == 0.135 and ratios["other-model"] == 1.5 and completions["deepseek-chat"] == 4   # 其他模型原样保留
    assert gw.audits[-1][0] == "model.pricing.set" and "0.14" in gw.audits[-1][1]


def test_set_pricing_without_output_uses_same_price_and_validates(gw):
    r = client.put("/api/models/pricing/deepseek-v4-flash", json={"input_per_m": 1})
    assert r.json()["output_per_m"] == 1.0
    for bad in ({"input_per_m": 0}, {"input_per_m": -1}, {"input_per_m": 20000}, {"input_per_m": 1, "output_per_m": 0}):
        assert client.put("/api/models/pricing/deepseek-v4-flash", json=bad).status_code == 400, bad
    assert client.put("/api/models/pricing/deepseek-v4-flash", json={"input_per_m": "abc"}).status_code == 422


def test_clear_pricing_restores_default_and_404_when_not_set(gw):
    assert client.delete("/api/models/pricing/deepseek-chat").status_code == 200
    assert "deepseek-chat" not in json.loads(gw.options["ModelRatio"]) and "deepseek-chat" not in json.loads(gw.options["CompletionRatio"])
    assert json.loads(gw.options["ModelRatio"])["other-model"] == 1.5
    assert client.delete("/api/models/pricing/deepseek-chat").status_code == 404
    assert gw.audits[-1][0] == "model.pricing.clear"


def test_broken_option_json_gives_a_clear_error_and_writes_nothing(gw):
    gw.options["ModelRatio"] = "{not json"
    r = client.put("/api/models/pricing/deepseek-v4-flash", json={"input_per_m": 1})
    assert r.status_code == 400 and "合法 JSON" in r.json()["detail"] and gw.puts == []
