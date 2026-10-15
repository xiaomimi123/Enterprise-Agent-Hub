import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app

client = TestClient(app)


@pytest.fixture
def casdoor_mode(monkeypatch):
    s = dataclasses.replace(auth.settings, mode="casdoor", casdoor_org="xinghe", casdoor_client_id="cid")
    monkeypatch.setattr(auth, "settings", s)


def fake_claims(monkeypatch, **claims):
    base = {"name": "admin", "owner": "xinghe", "displayName": "管理员", "isAdmin": True}
    monkeypatch.setattr(auth, "decode_token", lambda token: base | claims)


def test_demo_mode_needs_no_login():
    assert client.get("/api/overview").status_code == 200
    assert client.get("/api/auth/me").json()["mode"] == "demo"


def test_requires_login(casdoor_mode):
    r = client.get("/api/overview")
    assert r.status_code == 401
    assert client.get("/api/health").status_code == 200


def test_admin_allowed(casdoor_mode, monkeypatch):
    fake_claims(monkeypatch)
    r = client.get("/api/auth/me", cookies={auth.SESSION_COOKIE: "t"})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "管理员"


def test_non_admin_forbidden(casdoor_mode, monkeypatch):
    fake_claims(monkeypatch, isAdmin=False)
    assert client.get("/api/overview", cookies={auth.SESSION_COOKIE: "t"}).status_code == 403


def test_other_org_forbidden(casdoor_mode, monkeypatch):
    fake_claims(monkeypatch, owner="built-in")
    assert client.get("/api/overview", cookies={auth.SESSION_COOKIE: "t"}).status_code == 403


def test_callback_rejects_bad_state(casdoor_mode):
    r = client.post("/api/auth/callback", json={"code": "x", "state": "y"}, cookies={auth.STATE_COOKIE: "z"})
    assert r.status_code == 400
