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


# ---- 总览的 14 天历史：在线人数与拦截次数 ----

def test_daily_ops_fills_gaps_and_orders_days():
    from datetime import date
    today = date(2026, 10, 19)
    out = presence.daily_ops({"2026-10-19": 3, "2026-10-17": 2}, {"2026-10-18": 4, "2026-10-19": 1}, today, days=4)
    assert out == [
        {"date": "2026-10-16", "online": 0, "denied": 0},
        {"date": "2026-10-17", "online": 2, "denied": 0},
        {"date": "2026-10-18", "online": 0, "denied": 4},
        {"date": "2026-10-19", "online": 3, "denied": 1},
    ]


def test_daily_ops_ignores_days_outside_window():
    from datetime import date
    out = presence.daily_ops({"2026-09-01": 9}, {}, date(2026, 10, 19), days=2)
    assert [d["online"] for d in out] == [0, 0] and len(out) == 2


def test_touch_presence_also_marks_the_day(monkeypatch):
    from app import db
    calls = []

    class Conn:
        def execute(self, sql, params=None):
            calls.append((sql, params))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(db, "connect", lambda: Conn())
    db.touch_presence("o", "u", client="WorkBuddy")
    assert any("agent_presence_daily" in sql for sql, _ in calls)
