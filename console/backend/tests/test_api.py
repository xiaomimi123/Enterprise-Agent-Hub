from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_all_read_endpoints():
    for path in ["/api/health", "/api/overview", "/api/departments", "/api/members", "/api/role-packs",
                 "/api/role-packs/rp-xhs-ops", "/api/catalog", "/api/skills", "/api/skills/xhs-cover",
                 "/api/knowledge-bases", "/api/knowledge-bases/kb-brand/documents", "/api/audit/traces",
                 "/api/audit/traces/tr-0001", "/api/usage?days=7"]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)


def test_demo_data_shape():
    assert len(client.get("/api/members").json()) == 50
    ov = client.get("/api/overview").json()
    assert ov["stats"]["denied_today"] >= 2
    assert ov["stats"]["pending_approvals"] >= 1


def test_assign_and_update_role_pack():
    m = client.get("/api/members", params={"dept": "tech"}).json()[0]
    r = client.put(f"/api/members/{m['id']}/role-pack", json={"role_pack_id": "rp-designer"})
    assert r.json()["role_pack"] == "rp-designer"
    r = client.patch("/api/role-packs/rp-cs", json={"monthly_quota": 450, "external_access": "关闭"})
    assert r.json()["monthly_quota"] == 450 and r.json()["external_access"] == "关闭"


def test_not_found():
    assert client.get("/api/skills/nope").status_code == 404
    assert client.patch("/api/role-packs/rp-cs", json={"monthly_quota": -1}).status_code == 400


def test_agent_script_is_downloadable_without_login():
    r = client.get("/api/agent/hub_agent.py")
    assert r.status_code == 200 and "def cmd_mcp" in r.text
    assert "attachment" in r.headers.get("content-disposition", "")


def test_connect_info_lists_endpoints():
    d = client.get("/api/connect").json()
    assert d["mcp_url"].endswith("/mcp") and d["api_base"].endswith("/api/v1")
    assert d["script_url"].endswith("/api/agent/hub_agent.py") and d["hub_url"]


def test_install_scripts_carry_hub_url():
    from app.config import settings
    for name, marker in (("install.ps1", "setup --hub"), ("install.sh", "setup --hub")):
        r = client.get(f"/api/agent/{name}")
        assert r.status_code == 200 and marker in r.text
        assert "__HUB_URL__" not in r.text and settings.public_url in r.text
        assert "charset=utf-8" in r.headers["content-type"]
    assert client.get("/api/agent/install.bat").status_code == 404


def test_agent_config_announces_connector_version(monkeypatch, tmp_path):
    """接入器靠 config 里的 agent_version 决定要不要自动更新自己：必须和挂载的脚本里的 VERSION 一致
    （没有灰度配置时；部署机上的 agent/rollout.json 不能影响这个测试，所以只复制脚本到临时目录）"""
    import dataclasses
    import re
    import shutil
    from pathlib import Path

    from app import agent_api
    from app.config import settings
    shutil.copy2(Path(settings.agent_dir) / "hub_agent.py", tmp_path / "hub_agent.py")
    monkeypatch.setattr(agent_api, "settings", dataclasses.replace(settings, agent_dir=str(tmp_path)))
    settings = agent_api.settings
    declared = re.search(r'^VERSION = "([^"]+)"', (Path(settings.agent_dir) / "hub_agent.py").read_text(encoding="utf-8"), re.M).group(1)
    assert agent_api._agent_version() == declared and declared
