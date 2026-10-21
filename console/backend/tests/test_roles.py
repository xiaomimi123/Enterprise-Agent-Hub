import dataclasses
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import auth, policy, roles, work

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone(timedelta(hours=8)))


def req(method, path):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


def gate(monkeypatch, scope, user=None):
    monkeypatch.setattr(auth, "settings", dataclasses.replace(auth.settings, mode="casdoor", casdoor_org="o"))
    monkeypatch.setattr(auth, "_authenticate", lambda r: user or {"name": "u", "org": "o", "is_admin": scope["role"] == "admin"})
    monkeypatch.setattr(auth.roles, "resolve", lambda org, name, is_admin=False: scope)


MANAGER = {"role": "manager", "depts": ["ops"]}
BOSS = {"role": "boss", "depts": None}
ADMIN = {"role": "admin", "depts": None}


@pytest.mark.parametrize("path", ["/api/departments", "/api/members", "/api/skills", "/api/skills/xhs-topic", "/api/knowledge-bases",
                                  "/api/knowledge-bases/kb1/documents", "/api/work/report", "/api/role-packs"])
def test_manager_can_read_the_allowlist(monkeypatch, path):
    gate(monkeypatch, MANAGER)
    assert auth.console_user(req("GET", path))["depts"] == ["ops"]


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/models/upstreams"), ("GET", "/api/connect"), ("GET", "/api/usage"), ("GET", "/api/audit/traces"), ("GET", "/api/overview"),
    ("GET", "/api/org"), ("PUT", "/api/org/bosses"), ("POST", "/api/members"), ("PATCH", "/api/role-packs/rp-1"), ("DELETE", "/api/members/x"),
    ("GET", "/api/members/x/password"), ("GET", "/api/future-admin-thing"), ("PUT", "/api/members/x/role-pack"),
])
def test_manager_is_denied_everything_else_by_default(monkeypatch, method, path):
    gate(monkeypatch, MANAGER)
    with pytest.raises(HTTPException) as e:
        auth.console_user(req(method, path))
    assert e.value.status_code == 403


def test_boss_reads_more_but_never_writes_or_touches_system_config(monkeypatch):
    gate(monkeypatch, BOSS)
    for p in ("/api/overview", "/api/usage", "/api/audit/traces", "/api/audit/traces/t1", "/api/work/report", "/api/apps"):
        assert auth.console_user(req("GET", p))["role"] == "boss"
    for method, p in (("GET", "/api/models/upstreams"), ("GET", "/api/connect"), ("GET", "/api/org"), ("POST", "/api/members"), ("PATCH", "/api/role-packs/x")):
        with pytest.raises(HTTPException):
            auth.console_user(req(method, p))


def test_admin_passes_everything_and_people_without_a_role_cannot_log_in(monkeypatch):
    gate(monkeypatch, ADMIN)
    assert auth.console_user(req("DELETE", "/api/members/x"))["role"] == "admin"
    gate(monkeypatch, {"role": None, "depts": []})
    with pytest.raises(HTTPException) as e:
        auth.console_user(req("GET", "/api/work/report"))
    assert e.value.status_code == 403


def test_roles_resolve(monkeypatch):
    monkeypatch.setattr(roles, "settings", dataclasses.replace(roles.settings, database_url="x"))
    rows = {"a": [{"role": "boss", "dept_id": ""}], "b": [{"role": "manager", "dept_id": "ops"}, {"role": "manager", "dept_id": "design"}], "c": []}
    monkeypatch.setattr(roles.db, "roles_of", lambda org, user: rows[user])
    assert roles.resolve("o", "z", is_admin=True) == {"role": "admin", "depts": None}
    assert roles.resolve("o", "a") == {"role": "boss", "depts": None}
    assert roles.resolve("o", "b") == {"role": "manager", "depts": ["design", "ops"]}
    assert roles.resolve("o", "c") == {"role": None, "depts": []}
    assert roles.can_see_dept({"depts": ["ops"]}, "ops") and not roles.can_see_dept({"depts": ["ops"]}, "hr") and roles.can_see_dept({"depts": None}, "hr")


def test_default_pack_prefers_console_config_then_builtin_then_fallback():
    assert policy.default_pack_id("ops", {"ops": "rp-custom"}) == "rp-custom"
    assert policy.default_pack_id("ops", {}) == policy.DEFAULT_ROLE_PACKS["ops"]
    assert policy.default_pack_id("brand-new") == policy.FALLBACK_ROLE_PACK and policy.default_pack_id("brand-new", {"x": "y"}) == policy.FALLBACK_ROLE_PACK


def test_work_report_for_a_manager_only_contains_their_departments():
    def ev(u, dept):
        return {"user_name": u, "display_name": u, "dept": dept, "tool": "kb.search", "result": "通过", "ts": NOW - timedelta(hours=1)}

    def item(u, dept):
        return {"id": 1, "user_name": u, "display_name": u, "dept": dept, "kind": "笔记", "title": "t", "status": "已完成", "progress": 100,
                "link": "", "note": "", "source": "agent", "updated_at": NOW - timedelta(hours=1)}
    r = work.build_report(days=1, events=[ev("a", "ops"), ev("b", "hr")], items=[item("a", "ops"), item("b", "hr")], tasks=[],
                          assignments={}, packs={"rp-general": {"name": "通用"}, "rp-xhs-ops": {"name": "运营"}}, now=NOW, depts=["ops"])
    assert [p["user_name"] for p in r["people"]] == ["a"] and r["totals"]["items"]["total"] == 1 and [i["user_name"] for i in r["items"]] == ["a"]
    assert work.build_report(days=1, events=[ev("a", "ops")], items=[], tasks=[], assignments={}, packs={}, now=NOW, depts=[])["people"] == []
