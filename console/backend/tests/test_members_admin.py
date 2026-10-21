"""成员管理：创建 / 修改 / 重置密码 / 停用 / 删除 / 批量导入，以及账号状态检查（停用即失效）。"""

import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app import accounts, members_admin, members_api
from app.config import settings
from app.main import app
from app.members_admin import MemberAdmin, MemberError

ORG = "xinghe"
http_client = TestClient(app)


class FakeCasdoor:
    """内存里的 Casdoor：用户、部门，按真实接口的路径和响应形状回应。"""

    def __init__(self):
        self.users = {"admin": {"owner": ORG, "name": "admin", "displayName": "管理员", "isAdmin": True, "isForbidden": False,
                                "groups": [f"{ORG}/ops"]}}
        self.groups = [{"name": "ops", "displayName": "运营部"}, {"name": "finance", "displayName": "财务部"}]
        self.passwords: dict[str, str] = {}
        self.client = httpx.Client(base_url="http://casdoor", transport=httpx.MockTransport(self.handle))

    def handle(self, r: httpx.Request) -> httpx.Response:
        ok = lambda data=None: httpx.Response(200, json={"status": "ok", "data": data})  # noqa: E731
        path = r.url.path
        q = dict(r.url.params)
        if path == "/api/get-groups":
            return ok(self.groups)
        if path == "/api/get-user":
            return ok(self.users.get(q["id"].split("/", 1)[1]))
        if path == "/api/add-user":
            u = json.loads(r.content)
            self.users[u["name"]] = u
            self.passwords[u["name"]] = u["password"]
            return ok()
        if path == "/api/update-user":
            u = json.loads(r.content)
            self.users[u["name"]] = u
            return ok()
        if path == "/api/set-password":
            form = dict(x.split("=", 1) for x in r.content.decode().split("&"))
            self.passwords[form["userName"]] = form["newPassword"]
            return ok()
        if path == "/api/delete-user":
            self.users.pop(json.loads(r.content)["name"], None)
            return ok()
        return httpx.Response(404)


class FakeNewApi:
    configured = True

    def __init__(self):
        self.deleted: list[tuple[str, str]] = []

    def delete_tokens_of(self, org, name):
        self.deleted.append((org, name))
        return 2


@pytest.fixture
def env():
    cas, na = FakeCasdoor(), FakeNewApi()
    return cas, na, MemberAdmin(client=cas.client, org=ORG, newapi=na)


def test_create_resolves_dept_forces_password_change_and_generates_password(env):
    cas, _, admin = env
    out = admin.create("Zhang.San", "张三", "财务部", title="出纳")
    u = cas.users["zhang.san"]
    assert out["id"] == "zhang.san" and out["dept"] == "finance" and u["groups"] == [f"{ORG}/finance"]
    assert u["needUpdatePassword"] is True and u["isForbidden"] is False and u["isAdmin"] is False
    pw = out["initial_password"]
    assert len(pw) == 10 and re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw) and cas.passwords["zhang.san"] == pw


def test_create_validation(env):
    _, _, admin = env
    for args, msg in ((("Bad Name!", "x", "ops"), "用户名"), (("ok1", "", "ops"), "姓名"), (("ok2", "x", "不存在的部门"), "不存在"),
                      (("ok3", "x", "ops", "", "", "", "short"), "至少 8 位"), (("ok4", "x", "ops", "", "", "", "onlyletters"), "字母和数字")):
        with pytest.raises(MemberError, match=msg):
            admin.create(*args)
    admin.create("dup1", "甲", "ops")
    with pytest.raises(MemberError, match="已存在"):
        admin.create("dup1", "乙", "ops")


def test_update_and_reset_password(env):
    cas, _, admin = env
    admin.create("lisi", "李四", "ops", password="Passw0rd1")
    admin.update("lisi", display_name="李四四", dept="finance", phone="13800000000")
    u = cas.users["lisi"]
    assert u["displayName"] == "李四四" and u["groups"] == [f"{ORG}/finance"] and u["phone"] == "13800000000"
    u["needUpdatePassword"] = False
    out = admin.reset_password("lisi")
    assert cas.users["lisi"]["needUpdatePassword"] is True and cas.passwords["lisi"] == out["initial_password"]
    with pytest.raises(MemberError, match="至少 8 位"):
        admin.reset_password("lisi", "abc1")


def test_disable_revokes_keys_and_guards(env):
    cas, na, admin = env
    admin.create("wang5", "王五", "ops")
    out = admin.set_enabled("wang5", False, acting="admin")
    assert cas.users["wang5"]["isForbidden"] is True and out["revoked_keys"] == 2 and na.deleted == [(ORG, "wang5")]
    assert admin.set_enabled("wang5", True, acting="admin")["enabled"] is True and cas.users["wang5"]["isForbidden"] is False
    with pytest.raises(MemberError, match="自己"):
        admin.set_enabled("admin", False, acting="admin")
    with pytest.raises(MemberError, match="管理员"):
        admin.set_enabled("admin", False, acting="someone")
    with pytest.raises(MemberError, match="不存在"):
        admin.set_enabled("nobody", False, acting="admin")


def test_delete_revokes_keys_and_guards(env):
    cas, na, admin = env
    admin.create("zhao6", "赵六", "ops")
    assert admin.remove("zhao6", acting="admin")["revoked_keys"] == 2
    assert "zhao6" not in cas.users and (ORG, "zhao6") in na.deleted
    with pytest.raises(MemberError, match="管理员"):
        admin.remove("admin", acting="x")


def test_csv_import_partial_failure_and_limits(env):
    cas, _, admin = env
    text = ("﻿username,display_name,dept,title,phone,email,password\n"
            "a1,甲,运营部,,,,\n"
            "a2,乙,ops,运营,13800000001,,Passw0rd9\n"
            "BAD NAME,丙,ops,,,,\n"
            "a4,丁,没有的部门,,,,\n"
            "a1,重复,ops,,,,\n")
    out = admin.import_rows(admin.parse_csv(text))
    assert out["created"] == 2 and out["failed"] == 3
    assert [r["row"] for r in out["results"] if not r["ok"]] == [4, 5, 6]
    assert cas.passwords["a2"] == "Passw0rd9" and out["results"][0]["initial_password"] == cas.passwords["a1"]
    with pytest.raises(MemberError, match="username"):
        MemberAdmin.parse_csv("name,dept\nx,ops\n")
    with pytest.raises(MemberError, match="没有读到"):
        MemberAdmin.parse_csv("username,display_name,dept\n")
    with pytest.raises(MemberError, match="最多"):
        MemberAdmin.parse_csv("username,display_name,dept\n" + "u,x,ops\n" * (members_admin.MAX_IMPORT_ROWS + 1))


# ---- 账号状态检查 ----

def test_is_active_blocks_forbidden_and_missing_caches_and_fails_open(monkeypatch):
    users = {"ok": {"isForbidden": False}, "banned": {"isForbidden": True}}
    calls = []

    def handler(r: httpx.Request) -> httpx.Response:
        name = r.url.params["id"].split("/", 1)[1]
        calls.append(name)
        if name == "boom":
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"status": "ok", "data": users.get(name)})

    monkeypatch.setattr(accounts, "_http", httpx.Client(base_url="http://c", transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(accounts, "settings", type("S", (), {"auth_enabled": True})())
    accounts._cache.clear()
    assert accounts.is_active(ORG, "ok") and not accounts.is_active(ORG, "banned") and not accounts.is_active(ORG, "ghost")
    n = len(calls)
    assert accounts.is_active(ORG, "ok") and len(calls) == n                 # 命中缓存
    users["ok"]["isForbidden"] = True
    assert accounts.is_active(ORG, "ok")                                      # 缓存期内仍是旧结果
    accounts.invalidate(ORG, "ok")
    assert not accounts.is_active(ORG, "ok")                                  # 清缓存后立即生效
    assert accounts.is_active(ORG, "boom")                                    # 身份服务出错：放行
    assert (ORG, "boom") not in accounts._cache                               # 且不缓存


# ---- 接口 ----

def test_routes_audit_without_password_and_demo_mode_refused(env, monkeypatch):
    cas, na, admin = env
    audits = []
    monkeypatch.setattr(members_api, "_audit", lambda user, tool, detail, result="通过": audits.append((tool, detail)))
    monkeypatch.setattr(members_api, "make_admin", lambda: admin)
    monkeypatch.setattr(members_api, "settings", type("S", (), {"mode": "demo", "database_url": ""})())
    assert http_client.post("/api/members", json={"username": "x1", "display_name": "x", "dept": "ops"}).status_code == 400
    monkeypatch.setattr(members_api, "settings", type("S", (), {"mode": "casdoor", "database_url": ""})())
    r = http_client.post("/api/members", json={"username": "x1", "display_name": "甲", "dept": "ops", "password": "Passw0rd1"})
    assert r.status_code == 200 and r.json()["initial_password"] == "Passw0rd1"
    assert http_client.post("/api/members", json={"username": "x1", "display_name": "甲", "dept": "ops"}).status_code == 400
    assert http_client.post("/api/members/x1/password", json={}).status_code == 200
    assert http_client.post("/api/members/x1/enabled", json={"enabled": False}).json()["revoked_keys"] == 2
    assert http_client.post("/api/members/import", content="username,display_name,dept\nx2,乙,ops\n",
                            headers={"content-type": "text/csv"}).json()["created"] == 1
    assert http_client.delete("/api/members/x1").status_code == 200
    assert {t for t, _ in audits} >= {"member.create", "member.password", "member.disable", "member.import", "member.delete"}
    assert all("Passw0rd1" not in d and cas.passwords["x2"] not in d for _, d in audits)
