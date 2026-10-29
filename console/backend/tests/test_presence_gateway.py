"""模型网关里的调用也算在线：从日志取每人最近一次调用、20 秒限流、网关出错不影响页面。"""
from datetime import datetime, timezone

from app import presence

ORG = "xinghe"


def log(token, ts, **extra):
    return {"token_name": token, "created_at": ts, **extra}


def test_last_call_by_user_takes_the_latest_per_employee_and_understands_session_keys():
    logs = [log("hub-xinghe-linjie", 1_000), log("hub-xinghe-linjie", 3_000), log("hub-xinghe-linjie~trace-ab12", 2_000),
            log("hub-xinghe-zrx", 2_500), log("hub-other-bob", 9_999), log("not-a-hub-key", 9_999), log("hub-xinghe-linjie", 0), {"created_at": 5}]
    got = presence.last_call_by_user(logs, ORG)
    assert set(got) == {"linjie", "zrx"}                            # 别的组织、不是中枢 key、没有时间的都忽略
    assert got["linjie"] == datetime.fromtimestamp(3_000, tz=timezone.utc)
    assert got["zrx"] == datetime.fromtimestamp(2_500, tz=timezone.utc)
    assert got["linjie"].tzinfo is not None


class FakeApi:
    def __init__(self, logs, configured=True, fail=False):
        self.logs, self.configured, self.fail, self.calls = logs, configured, fail, []

    def recent_logs(self, since):
        self.calls.append(since)
        if self.fail:
            raise RuntimeError("网关暂时不可用")
        return self.logs


def fresh():
    presence._gateway_polled_at = 0.0


def test_sync_touches_each_user_with_the_time_of_their_last_call():
    fresh()
    touched = []
    api = FakeApi([log("hub-xinghe-linjie", 5_000), log("hub-xinghe-zrx", 4_000)])
    n = presence.sync_from_gateway(ORG, client=api, touch=lambda o, u, t: touched.append((o, u, int(t.timestamp()))), now=10_000)
    assert n == 2 and sorted(touched) == [(ORG, "linjie", 5_000), (ORG, "zrx", 4_000)]
    assert api.calls == [10_000 - presence.GATEWAY_WINDOW_SECONDS]   # 只读最近 10 分钟


def test_sync_is_throttled_to_once_per_20_seconds():
    fresh()
    api = FakeApi([log("hub-xinghe-linjie", 5_000)])
    assert presence.sync_from_gateway(ORG, client=api, touch=lambda *a: None, now=1_000) == 1
    assert presence.sync_from_gateway(ORG, client=api, touch=lambda *a: None, now=1_015) == 0   # 20 秒内：不再读网关
    assert presence.sync_from_gateway(ORG, client=api, touch=lambda *a: None, now=1_021) == 1
    assert len(api.calls) == 2


def test_sync_never_breaks_the_page_when_gateway_or_database_fails_or_is_not_configured():
    fresh()
    assert presence.sync_from_gateway(ORG, client=FakeApi([], fail=True), touch=lambda *a: None, now=1_000) == 0
    fresh()
    assert presence.sync_from_gateway(ORG, client=FakeApi([log("hub-xinghe-a", 1)], configured=False), touch=lambda *a: None, now=1_000) == 0
    fresh()

    def boom(*a):
        raise RuntimeError("数据库不可用")
    assert presence.sync_from_gateway(ORG, client=FakeApi([log("hub-xinghe-a", 1)]), touch=boom, now=1_000) == 0


def test_a_gateway_call_within_five_minutes_makes_member_online_and_older_does_not():
    now = datetime.now(timezone.utc)
    fresh_row = {"last_seen": now, "client": None, "version": None, "os": None}
    old_row = {"last_seen": datetime.fromtimestamp(now.timestamp() - 6 * 60, tz=timezone.utc), "client": "CodeBuddy CLI", "version": "0.5.10", "os": "Windows 11"}
    assert presence.member_agent(fresh_row, now)["agent_status"] == "在线"
    assert presence.member_agent(fresh_row, now)["os"] == "官方 agent"        # 只有网关信号时不知道用的哪个 agent，沿用原来的显示
    assert presence.member_agent(old_row, now)["agent_status"] == "离线"


def test_heartbeat_body_may_be_empty_so_the_workbench_does_not_overwrite_the_connector_version():
    from app.agent_api import Heartbeat
    hb = Heartbeat.model_validate({})
    assert (hb.client, hb.version, hb.os) == ("", "", "")        # 空值走 touch_presence 的 `or None`，库里原来的值保留


def test_latest_activity_takes_the_latest_of_signin_presence_and_audit_event():
    """成员页「最近活跃」曾只读 Casdoor 的 lastSigninTime（10-21），而同一个人今天还在用工作台。"""
    signin = "2026-10-21T09:32:46+08:00"
    seen = datetime(2026, 10, 29, 1, 48, 23, tzinfo=timezone.utc)          # 09:48 +08:00
    event = datetime(2026, 10, 29, 1, 47, 6, tzinfo=timezone.utc)
    assert presence.latest_activity(signin, seen, event) == seen.isoformat()
    assert presence.latest_activity(signin, None, event) == event.isoformat()
    assert presence.latest_activity(signin, None, None) == datetime.fromisoformat(signin).isoformat()   # 只有登录时间：照旧
    assert presence.latest_activity(None, None, None) is None
    assert presence.latest_activity("not a date", None, event) == event.isoformat()                      # 坏数据忽略
    assert presence.latest_activity("2026-10-30T00:00:00Z", seen, event) == "2026-10-30T00:00:00+00:00"   # 登录时间最晚就用登录时间
    naive = datetime(2026, 10, 29, 3, 0, 0)                                                              # 没有时区的按 UTC 处理，不抛异常
    assert presence.latest_activity(None, naive, None) == naive.replace(tzinfo=timezone.utc).isoformat()


def test_health_and_member_pages_use_the_same_online_window():
    """应用健康页原来是 3 分钟、成员页和总览是 5 分钟：同一个人可能一个页面在线、另一个离线。"""
    from app import health
    assert health.ONLINE_SECONDS == presence.ONLINE_MINUTES * 60 == 300
