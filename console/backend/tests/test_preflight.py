"""安装前自检：错误码目录、匿名上报的清洗、自检脚本的下发。"""
from app import health


def test_preflight_codes_all_have_label_and_fix():
    codes = {k: v for k, v in health.CODES.items() if k.startswith("PREFLIGHT_")}
    assert len(codes) >= 15
    assert all(label and fix for label, fix in codes.values())


def test_preflight_events_keep_only_known_preflight_codes_and_redact():
    dev, events = health.preflight_events({"device_id": "ab-12!", "os": "Windows 10", "results": [
        {"code": "PREFLIGHT_DISK_LOW", "message": "C:/Users/bob/HubApps 100 MB"},
        {"code": "NODE_MISSING", "message": "不是自检的码"},
        {"code": "PREFLIGHT_UNKNOWN_CODE"},
        "不是字典",
        {"code": "preflight_no_edge", "message": "x@y.com"},
    ]})
    assert dev == "ab12"
    assert [e["code"] for e in events] == ["PREFLIGHT_DISK_LOW", "PREFLIGHT_NO_EDGE"]
    assert all(e["stage"] == "preflight" and e["ok"] is False and e["device_id"] == "ab12" for e in events)
    assert events[0]["message"].startswith("~/")          # 用户目录被换成 ~
    assert "@y.com" not in events[1]["message"] and "***@***" in events[1]["message"]


def test_preflight_events_cap_batch_and_empty_body():
    assert health.preflight_events({})[1] == []
    _, events = health.preflight_events({"device_id": "d", "results": [{"code": "PREFLIGHT_NO_EDGE"}] * 80})
    assert len(events) == 50


def test_preflight_script_is_served_with_hub_url_and_zh_json():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import agent_api
    from app.config import settings

    app = FastAPI()
    app.include_router(agent_api.router)
    r = TestClient(app).get("/api/agent/preflight.ps1")
    assert r.status_code == 200
    assert "__HUB_URL__" not in r.text and "__ZH_JSON__" not in r.text
    assert settings.public_url.rstrip("/") in r.text
    assert r.text.isascii()                                # 中文必须是 \u 转义，不然 PowerShell 5 管道执行会乱码
    assert "PREFLIGHT_DISK_LOW" in r.text
