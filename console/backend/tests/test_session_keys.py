"""会话专属 key：把追踪 ID 编进 key 名，模型调用日志的 token_name 就能精确归属到链路。"""

import dataclasses
from datetime import datetime, timedelta

import httpx
from fastapi.testclient import TestClient

from app import agent_api, db, newapi
from app.main import app

client = TestClient(app)
NOW = datetime.now().astimezone()


def iso(sec):
    return (NOW + timedelta(seconds=sec)).replace(microsecond=0).isoformat()


# ---- 命名与解析 ----

def test_session_name_roundtrip():
    n = newapi.session_token_name("xinghe", "zhouyinuo", "tr-1a2b3c4d5e6f")
    assert n == "hub-xinghe-zhouyinuo~tr-1a2b3c4d5e6f" and len(n) <= 50
    assert newapi.user_from_token_name(n, "xinghe") == "zhouyinuo"          # 用量按人统计时去掉会话后缀
    assert newapi.trace_from_token_name(n) == "tr-1a2b3c4d5e6f"
    assert newapi.trace_from_token_name("hub-xinghe-zhouyinuo") is None
    assert newapi.user_from_token_name("hub-xinghe-zhouyinuo", "xinghe") == "zhouyinuo"


def test_session_name_stays_within_limit_for_long_users():
    n = newapi.session_token_name("xinghe", "a" * 60, "tr-1a2b3c4d5e6f")
    assert len(n) <= 50 and n.endswith("~tr-1a2b3c4d5e6f")


def test_session_name_rejects_unsafe_trace_ids():
    n = newapi.session_token_name("o", "u", "tr-1/../x y")        # 追踪 ID 来自请求头，不可信：只留安全字符
    assert "/" not in n and " " not in n and n.startswith("hub-o-u~")


# ---- 用量合计：基础 key + 所有会话 key ----

def test_month_used_sums_base_and_session_keys(monkeypatch):
    now = datetime.now().timestamp()
    logs = [{"token_name": "hub-o-u", "quota": 100, "created_at": now},
            {"token_name": "hub-o-u~tr-aaaa", "quota": 200, "created_at": now},
            {"token_name": "hub-o-u~tr-bbbb", "quota": 300, "created_at": now},
            {"token_name": "hub-o-other~tr-cccc", "quota": 999, "created_at": now},
            {"token_name": "hub-o-u2", "quota": 999, "created_at": now},          # 前缀相同但是另一个人
            {"token_name": "hub-o-u", "quota": 999, "created_at": now - 90 * 86400}]  # 上个月
    na = newapi.NewApi("http://x", "t", "1")
    monkeypatch.setattr(na, "logs", lambda days=31, **k: logs)
    assert na.month_used_quota("hub-o-u") == 600


# ---- 过期会话 key 的清理 ----

def test_purge_deletes_only_expired_session_keys(monkeypatch):
    na = newapi.NewApi("http://purge-test", "t", "1")
    now = int(datetime.now().timestamp())
    toks = [{"id": 1, "name": "hub-o-u", "expired_time": -1},                        # 基础 key：永不动
            {"id": 2, "name": "hub-o-u~tr-old", "expired_time": now - 10},           # 已过期：删
            {"id": 3, "name": "hub-o-u~tr-live", "expired_time": now + 3600},        # 未过期：留
            {"id": 4, "name": "hub-o-other~tr-old", "expired_time": now - 10}]       # 别人的：不碰
    monkeypatch.setattr(na, "_call", lambda method, path, **kw: {"items": toks} if method == "GET" else None)
    deleted = []
    monkeypatch.setattr(na.http, "delete", lambda path, **kw: deleted.append(path) or httpx.Response(200, json={"success": True}))
    assert na.purge_expired_sessions("hub-o-u") == 1 and deleted == ["/api/token/2"]


# ---- 精确归属优先于时间窗 ----

def test_exact_trace_match_beats_time_window():
    t1 = {"id": "tr-aaaa", "member_id": "u", "channel": "官方 agent", "tokens": 0, "cost": 0.0,
          "steps": [{"time": iso(0), "kind": "登录", "tool": "x", "detail": "", "result": "通过", "tokens": 0, "model": None, "cost": 0.0}]}
    t2 = {**t1, "id": "tr-bbbb", "steps": [{**t1["steps"][0], "time": iso(5)}]}   # 与 t1 时间上紧挨着
    ts = NOW.timestamp()
    logs = [
        {"token_name": "hub-o-u~tr-aaaa", "created_at": ts + 200, "model_name": "m", "prompt_tokens": 1, "completion_tokens": 1, "quota": 0},
        {"token_name": "hub-o-u~tr-bbbb", "created_at": ts + 3, "model_name": "m", "prompt_tokens": 2, "completion_tokens": 2, "quota": 0},
        {"token_name": "hub-o-u", "created_at": ts + 7, "model_name": "m", "prompt_tokens": 4, "completion_tokens": 4, "quota": 0},
    ]
    db.attach_model_calls([t1, t2], logs, "o", 7.2)
    # tr-aaaa 的调用发生在 +200 秒、tr-bbbb 的窗口里，但 key 名写明归 tr-aaaa；tr-bbbb 的调用发生在 +3 秒（t1 的窗口里），key 名写明归 tr-bbbb
    assert [s["tokens"] for s in t1["steps"] if s["kind"] == "模型"] == [2]
    assert [s["tokens"] for s in t2["steps"] if s["kind"] == "模型"] == [4, 8]


def test_session_log_without_matching_trace_is_dropped_not_misfiled():
    t1 = {"id": "tr-aaaa", "member_id": "u", "channel": "官方 agent", "tokens": 0, "cost": 0.0,
          "steps": [{"time": iso(0), "kind": "登录", "tool": "x", "detail": "", "result": "通过", "tokens": 0, "model": None, "cost": 0.0}]}
    logs = [{"token_name": "hub-o-u~tr-gone", "created_at": NOW.timestamp() + 5, "model_name": "m", "prompt_tokens": 9, "completion_tokens": 9, "quota": 0}]
    db.attach_model_calls([t1], logs, "o", 7.2)
    assert t1["tokens"] == 0 and len(t1["steps"]) == 1       # 属于别的（已不存在的）链路，不能按时间窗硬塞给 t1


# ---- enroll：只有 chat（会话 key 标记）才签发会话 key ----

def _enroll(monkeypatch, headers):
    claims = {"owner": "o", "name": "u", "displayName": "U", "groups": ["o/ops"]}
    monkeypatch.setattr(agent_api, "_verify_agent_token", lambda auth: claims)
    monkeypatch.setattr(agent_api.policy, "resolve_pack", lambda org, user, dept: {
        "name": "运营", "skills": [], "tools": [], "max_action_level": "需确认", "model_mode": "中枢模型",
        "models": ["deepseek-v4-flash"], "monthly_quota": 72})
    monkeypatch.setattr(agent_api.db, "add_audit", lambda **e: None)
    monkeypatch.setattr(agent_api, "settings", dataclasses.replace(agent_api.settings, default_model="deepseek-v4-flash", usd_cny=7.2))
    seen = {}

    class Fake:
        configured = True

        def available_models(self):
            return ["deepseek-v4-flash"]

        def month_used_quota(self, base):
            seen["used_for"] = base
            return 0

        def purge_expired_sessions(self, base):
            seen["purged"] = base

        def ensure_token(self, name, models=None, remain_quota=None, unlimited=True, expires_in=None):
            seen.update(name=name, expires_in=expires_in)
            return "sk-x"
    monkeypatch.setattr(agent_api, "NewApi", Fake)
    r = client.post("/api/agent/enroll", headers={"Authorization": "Bearer x", **headers})
    assert r.status_code == 200
    return seen


def test_enroll_issues_session_key_for_chat(monkeypatch):
    seen = _enroll(monkeypatch, {"X-Hub-Trace-Id": "tr-1a2b3c4d5e6f", "X-Hub-Key-Scope": "session"})
    assert seen["name"] == "hub-o-u~tr-1a2b3c4d5e6f" and seen["expires_in"] == 3 * 86400
    assert seen["used_for"] == "hub-o-u" and seen["purged"] == "hub-o-u"


def test_enroll_keeps_base_key_otherwise(monkeypatch):
    seen = _enroll(monkeypatch, {"X-Hub-Trace-Id": "tr-1a2b3c4d5e6f"})          # 普通 sync / 桥接：不加会话标记
    assert seen["name"] == "hub-o-u" and seen["expires_in"] is None


# ---- 不再依赖会被全局限流的 /api/token/search ----

def _na_with(monkeypatch, pages, calls):
    na = newapi.NewApi(f"http://cache-{len(calls)}-{id(pages)}", "t", "1")

    def fake_call(method, path, **kw):
        calls.append((method, path, kw.get("params")))
        assert path != "/api/token/search", "搜索接口全局限流（约 10 次 / 分钟），不能用"
        page = kw["params"]["p"]
        return {"items": pages.get(page, []), "total": sum(len(v) for v in pages.values()), "page": page, "page_size": 100}
    monkeypatch.setattr(na, "_call", fake_call)
    return na


def test_find_token_pages_through_list_and_caches(monkeypatch):
    calls = []
    page1 = [{"id": i, "name": f"hub-o-x{i}", "expired_time": -1} for i in range(100)]
    na = _na_with(monkeypatch, {0: page1, 1: [{"id": 500, "name": "hub-o-u", "expired_time": -1}]}, calls)
    assert na.find_token("hub-o-u")["id"] == 500           # 在第二页
    assert na.find_token("hub-o-x7")["id"] == 7            # 命中缓存，不再请求
    assert len(calls) == 2
    assert na.find_token("hub-o-missing") is None


def test_purge_uses_cached_list_and_forgets_deleted(monkeypatch):
    calls = []
    now = int(datetime.now().timestamp())
    pages = {0: [{"id": 1, "name": "hub-o-u", "expired_time": -1},
                 {"id": 2, "name": "hub-o-u~tr-old", "expired_time": now - 5}]}
    na = _na_with(monkeypatch, pages, calls)

    def fake_delete(path, **kw):  # 真实服务器删除后不会再列出
        pages[0] = [t for t in pages[0] if f"/api/token/{t['id']}" != path]
        return httpx.Response(200, json={"success": True})
    monkeypatch.setattr(na.http, "delete", fake_delete)
    assert na.purge_expired_sessions("hub-o-u") == 1
    assert na.find_token("hub-o-u~tr-old") is None          # 已删除的不应再从缓存里返回


def test_rate_limited_response_becomes_clear_error():
    import pytest
    na = newapi.NewApi("http://x", "t", "1")
    na.http = httpx.Client(base_url="http://x", transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(newapi.NewApiError, match="429"):
        na._call("GET", "/api/channel/")
