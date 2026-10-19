"""open_app：岗位包 apps 权限 → 启动凭证 + 审计；回报接口；岗位包编辑接受 apps。"""

import dataclasses
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import agent_api, app_access, apps, mcp_server, policy
from app.main import app

client = TestClient(app)


@pytest.fixture
def env(tmp_path, monkeypatch):
    d = tmp_path / "xhs-workbench"
    d.mkdir()
    (d / "app.json").write_text(json.dumps({
        "id": "xhs-workbench", "name": "小红书运营工作台", "version": "0.6.1", "description": "d",
        "entry": "xhs-workbench/scripts/workbench.mjs", "requires": {"node": ">=18"}, "setup_args": ["setup"], "start_args": ["start", "--open"]}), encoding="utf-8")
    with zipfile.ZipFile(d / "0.6.1.zip", "w") as z:
        z.writestr("xhs-workbench/scripts/workbench.mjs", "x")
    s = dataclasses.replace(apps.settings, apps_dir=str(tmp_path), file_secret="sec", public_url="http://hub:8088")
    monkeypatch.setattr(apps, "settings", s)
    audits = []
    monkeypatch.setattr(app_access, "_audit", lambda **e: audits.append(e))
    return audits


def principal(channel=policy.OFFICIAL, **pack):
    return policy.Principal(org="o", user_name="u", display_name="U", dept="ops", channel=channel,
                            pack={"name": "运营", "apps": ["xhs-workbench"], **pack})


def test_ticket_has_everything_the_connector_needs(env):
    t = app_access.ticket_for(principal(), "tr-1", "xhs-workbench")
    a = apps.get_app("xhs-workbench")
    assert t["app_id"] == "xhs-workbench" and t["version"] == "0.6.1" and t["name"] == "小红书运营工作台"
    assert t["sha256"] == apps.sha256_of(a.zip_path) and t["entry"] == "xhs-workbench/scripts/workbench.mjs"
    assert t["requires"] == {"node": ">=18"} and t["start_args"] == ["start", "--open"]
    exp, sig = [p.split("=")[1] for p in t["download_url"].split("?")[1].split("&")]
    assert apps.verify_zip_request("xhs-workbench", "0.6.1", int(exp), sig) == a.zip_path     # 链接真的能下载
    assert env[-1]["result"] == "通过" and env[-1]["tool"] == "app.open" and env[-1]["trace_id"] == "tr-1"


def test_pack_without_the_app_is_denied_with_reason_and_audit(env):
    with pytest.raises(app_access.AppDenied, match="没有打开「小红书运营工作台」的权限"):
        app_access.ticket_for(principal(apps=[]), "tr-1", "xhs-workbench")
    assert env[-1]["result"] == "拒绝" and env[-1]["kind"] == "拦截"


def test_external_agents_are_always_denied(env):
    with pytest.raises(app_access.AppDenied):
        app_access.ticket_for(principal(channel=policy.EXTERNAL), "tr-1", "xhs-workbench")
    assert env[-1]["result"] == "拒绝"


def test_unknown_app_gets_clear_message(env):
    with pytest.raises(app_access.AppDenied, match="没有这个应用"):
        app_access.ticket_for(principal(), "tr-1", "nope")


def test_list_for_only_returns_allowed_apps(env):
    assert [x["id"] for x in app_access.list_for(principal())] == ["xhs-workbench"]
    assert app_access.list_for(principal(apps=[])) == []


def test_mcp_open_app_text_tells_non_bridge_clients_what_to_do(env, monkeypatch):
    monkeypatch.setattr(mcp_server, "_principal", lambda: principal())
    monkeypatch.setattr(mcp_server, "_trace", lambda ctx: ("tr-9", ""))
    out = json.loads(mcp_server.open_app("xhs-workbench", ctx=None))
    assert out["app_id"] == "xhs-workbench" and out["needs_local_connector"] is True
    assert "hub_agent.py open-app xhs-workbench" in out["terminal_hint"]
    denied = mcp_server.open_app("nope", ctx=None)
    assert "没有这个应用" in denied and not denied.lstrip().startswith("{")           # 拒绝是纯文本，桥据此原样透传


def test_app_event_requires_token_and_writes_audit(monkeypatch):
    assert client.post("/api/agent/app-event", json={"app_id": "x", "version": "1", "ok": True}).status_code == 401
    claims = {"owner": "o", "name": "u", "displayName": "U", "groups": ["o/ops"]}
    monkeypatch.setattr(agent_api, "_verify_agent_token", lambda auth: claims)
    monkeypatch.setattr(agent_api.policy, "resolve_pack", lambda org, user, dept: {"name": "运营"})
    seen = []
    monkeypatch.setattr(agent_api.db, "add_audit", lambda **e: seen.append(e))
    r = client.post("/api/agent/app-event", headers={"Authorization": "Bearer x", "X-Hub-Trace-Id": "tr-7"},
                    json={"app_id": "xhs-workbench", "version": "0.6.1", "ok": False, "reason": "缺少 Node.js"})
    assert r.status_code == 200
    assert seen[-1]["trace_id"] == "tr-7" and seen[-1]["result"] == "拒绝" and "缺少 Node.js" in seen[-1]["detail"]
    client.post("/api/agent/app-event", headers={"Authorization": "Bearer x"},
                json={"app_id": "xhs-workbench", "version": "0.6.1", "ok": True, "url": "http://127.0.0.1:17890/"})
    assert seen[-1]["result"] == "通过" and "127.0.0.1:17890" in seen[-1]["detail"]


def test_role_pack_patch_accepts_registered_apps_only(env):
    r = client.patch("/api/role-packs/rp-xhs-ops", json={"apps": ["xhs-workbench"]})
    assert r.status_code == 200 and r.json()["apps"] == ["xhs-workbench"]
    assert client.patch("/api/role-packs/rp-xhs-ops", json={"apps": ["not-registered"]}).status_code == 400
    assert client.patch("/api/role-packs/rp-xhs-ops", json={"apps": []}).json()["apps"] == []
    client.patch("/api/role-packs/rp-xhs-ops", json={"apps": ["xhs-workbench"]})        # 演示数据是进程内共享的，恢复原值


def test_rest_open_app_returns_ticket_or_403(env, monkeypatch):
    assert client.post("/api/agent/open-app", json={"app_id": "xhs-workbench"}).status_code == 401      # 没有令牌
    claims = {"owner": "o", "name": "u", "displayName": "U", "groups": ["o/ops"]}
    monkeypatch.setattr(agent_api, "_verify_agent_token", lambda auth: claims)
    monkeypatch.setattr(agent_api.policy, "resolve_pack", lambda org, user, dept: {"name": "运营", "apps": ["xhs-workbench"]})
    ok = client.post("/api/agent/open-app", headers={"Authorization": "Bearer x", "X-Hub-Trace-Id": "tr-5"}, json={"app_id": "xhs-workbench"})
    assert ok.status_code == 200 and ok.json()["version"] == "0.6.1" and ok.json()["setup_args"] == ["setup"]
    monkeypatch.setattr(agent_api.policy, "resolve_pack", lambda org, user, dept: {"name": "财务", "apps": []})
    denied = client.post("/api/agent/open-app", headers={"Authorization": "Bearer x"}, json={"app_id": "xhs-workbench"})
    assert denied.status_code == 403 and "没有打开" in denied.json()["detail"]


def test_apps_listing_for_console(env, monkeypatch):
    r = client.get("/api/apps")
    assert r.status_code == 200
    [a] = r.json()
    assert a["id"] == "xhs-workbench" and a["name"] == "小红书运营工作台" and a["version"] == "0.6.1"
    assert len(a["sha256"]) == 64 and a["size"] > 0
    assert {"id": "rp-xhs-ops", "name": "小红书运营"} in a["allowed_packs"]           # 演示数据里运营岗位包放行了它
    assert a["opens_7d"] == 0 and a["last_open"] is None


def test_apps_listing_counts_only_successful_opens(env, monkeypatch):
    from datetime import datetime, timedelta
    from app import main
    now = datetime.now().astimezone()
    events = [{"tool": "app.open", "result": "通过", "ts": now - timedelta(days=1), "detail": "打开应用「小红书运营工作台」v0.6.1"},
              {"tool": "app.open", "result": "通过", "ts": now, "detail": "打开应用「小红书运营工作台」v0.6.1"},
              {"tool": "app.open", "result": "拒绝", "ts": now, "detail": "申请打开应用「小红书运营工作台」：没有权限"},
              {"tool": "app.open", "result": "通过", "ts": now - timedelta(days=9), "detail": "打开应用「小红书运营工作台」v0.6.0"}]
    monkeypatch.setattr(main, "_app_events", lambda days: events)
    [a] = client.get("/api/apps").json()
    assert a["opens_7d"] == 2 and a["last_open"] is not None
