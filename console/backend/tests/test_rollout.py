"""接入器灰度与回滚：谁拿到哪个版本。没有 rollout.json 时必须和以前一模一样。"""
import dataclasses
import json

from fastapi.testclient import TestClient

from app import agent_api, rollout
from app.main import app

client = TestClient(app)


def agent_dir(tmp_path, mounted="0.5.12", rollout_cfg=None, snapshots=()):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "hub_agent.py").write_text(f'VERSION = "{mounted}"\n# mounted\n', encoding="utf-8")
    for v in snapshots:
        d = tmp_path / "releases" / v
        d.mkdir(parents=True)
        (d / "hub_agent.py").write_text(f'VERSION = "{v}"\n# snapshot\n', encoding="utf-8")
    if rollout_cfg is not None:
        (tmp_path / "rollout.json").write_text(rollout_cfg if isinstance(rollout_cfg, str) else json.dumps(rollout_cfg), encoding="utf-8")
    return tmp_path


def point(monkeypatch, d):
    monkeypatch.setattr(agent_api, "settings", dataclasses.replace(agent_api.settings, agent_dir=str(d)))


def test_without_rollout_file_everything_is_as_before(tmp_path):
    d = agent_dir(tmp_path)
    assert rollout.load(d) is None
    assert rollout.choose(d, "anyone") == {"version": "0.5.12", "force": False}
    assert rollout.stable_version(d) == "0.5.12"
    assert rollout.script_for(d) == d / "hub_agent.py"


def test_canary_users_get_candidate_everyone_else_stable(tmp_path):
    d = agent_dir(tmp_path, rollout_cfg={"stable": "0.5.11", "candidate": "0.5.12", "canary_users": ["alice"]}, snapshots=["0.5.11"])
    assert rollout.choose(d, "alice") == {"version": "0.5.12", "force": False}
    assert rollout.choose(d, "bob") == {"version": "0.5.11", "force": False}
    assert rollout.choose(d, None) == {"version": "0.5.11", "force": False}      # 匿名按普通员工
    assert rollout.stable_version(d) == "0.5.11"                                  # 老接入器问到的版本


def test_rollback_marks_force_for_stable_only(tmp_path):
    d = agent_dir(tmp_path, rollout_cfg={"stable": "0.5.11", "candidate": "0.5.12", "canary_users": ["alice"], "force_stable": True}, snapshots=["0.5.11"])
    assert rollout.choose(d, "bob") == {"version": "0.5.11", "force": True}
    assert rollout.choose(d, "alice") == {"version": "0.5.12", "force": False}    # 灰度的人还在试 candidate，不强制


def test_script_for_serves_snapshots_only_for_listed_versions(tmp_path):
    d = agent_dir(tmp_path, rollout_cfg={"stable": "0.5.11", "candidate": "0.5.12"}, snapshots=["0.5.11"])
    assert rollout.script_for(d) == d / "releases" / "0.5.11" / "hub_agent.py"    # 默认 stable
    assert rollout.script_for(d, "0.5.12") == d / "hub_agent.py"                  # candidate 没快照但挂载的就是它
    assert rollout.script_for(d, "0.4.0") is None                                 # 没列出的版本
    assert rollout.script_for(d, "../../etc") is None
    d2 = agent_dir(tmp_path / "x", mounted="0.5.12", rollout_cfg={"stable": "0.5.11"})      # stable 没有快照、挂载的也不是它
    assert rollout.script_for(d2) is None


def test_broken_rollout_file_falls_back_instead_of_breaking_downloads(tmp_path):
    for bad in ("不是 json", '{"stable": "latest"}', '{"stable": "0.5.11", "canary_users": "alice"}', '{"candidate": "0.5.12"}'):
        d = agent_dir(tmp_path / str(abs(hash(bad))), rollout_cfg=bad)
        assert rollout.load(d) is None
        assert rollout.choose(d, "bob")["version"] == "0.5.12"


def test_endpoints_old_clients_only_see_stable_new_clients_ask_update(tmp_path, monkeypatch):
    d = agent_dir(tmp_path, rollout_cfg={"stable": "0.5.11", "candidate": "0.5.12", "canary_users": ["alice"]}, snapshots=["0.5.11"])
    point(monkeypatch, d)
    monkeypatch.setattr(agent_api, "_agent_client", lambda: ("cid", "sec"))
    assert client.get("/api/agent/config").json()["agent_version"] == "0.5.11"
    assert 'VERSION = "0.5.11"' in client.get("/api/agent/hub_agent.py").text       # 老接入器下载到的是 stable 快照，不是挂载的 0.5.12
    assert 'VERSION = "0.5.12"' in client.get("/api/agent/hub_agent.py?version=0.5.12").text
    assert client.get("/api/agent/hub_agent.py?version=9.9.9").status_code == 404
    assert client.get("/api/agent/update").json() == {"version": "0.5.11", "force": False}    # 无令牌 = 普通员工
    monkeypatch.setattr(agent_api, "_verify_agent_token", lambda a: {"name": "alice"})
    assert client.get("/api/agent/update", headers={"Authorization": "Bearer x"}).json() == {"version": "0.5.12", "force": False}


def test_latest_connector_for_outdated_flag_is_stable_not_candidate(tmp_path, monkeypatch):
    from app import health_api
    d = agent_dir(tmp_path, rollout_cfg={"stable": "0.5.11", "candidate": "0.5.12"}, snapshots=["0.5.11"])
    monkeypatch.setattr(health_api, "settings", dataclasses.replace(health_api.settings, agent_dir=str(d)))
    assert health_api.latest_connector() == "0.5.11"
