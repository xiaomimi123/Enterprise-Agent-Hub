"""员工端在线状态：接入器定时报到 + 官方 agent 调用中枢工具，都算在线。"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import agent_api, presence
from app.main import app

client = TestClient(app)
NOW = datetime.now().astimezone()


def test_heartbeat_requires_agent_token():
    assert client.post("/api/agent/heartbeat", json={}).status_code == 401


def test_heartbeat_records_client_version_os(monkeypatch):
    got = {}
    monkeypatch.setattr(agent_api, "_verify_agent_token", lambda auth: {"owner": "o", "name": "u"})
    monkeypatch.setattr(agent_api.db, "touch_presence", lambda org, user, **kw: got.update(org=org, user=user, **kw))
    r = client.post("/api/agent/heartbeat", headers={"Authorization": "Bearer x"},
                    json={"client": "WorkBuddy", "version": "0.4.0", "os": "Windows 10", "extra": "忽略"})
    assert r.status_code == 200
    assert got == {"org": "o", "user": "u", "client": "WorkBuddy", "version": "0.4.0", "os": "Windows 10"}


def test_status_from_presence():
    assert presence.member_agent(None, NOW) == {"agent_status": "未安装", "agent_version": "", "os": ""}
    row = {"last_seen": NOW - timedelta(minutes=2), "client": "WorkBuddy", "version": "0.4.0", "os": "Windows 10"}
    assert presence.member_agent(row, NOW) == {"agent_status": "在线", "agent_version": "0.4.0", "os": "WorkBuddy · Windows 10"}
    assert presence.member_agent({**row, "last_seen": NOW - timedelta(minutes=6)}, NOW)["agent_status"] == "离线"
    # 只通过 MCP 调用出现过（没有接入器信息）：仍然算在线，但不显示版本
    bare = presence.member_agent({"last_seen": NOW, "client": None, "version": None, "os": None}, NOW)
    assert bare == {"agent_status": "在线", "agent_version": "", "os": "官方 agent"}
