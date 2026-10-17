"""岗位包的可用模型与每人月模型额度落到 New API 的员工 key 上。"""

import dataclasses

from fastapi.testclient import TestClient

from app import agent_api, newapi
from app.main import app

client = TestClient(app)
AVAIL = ["deepseek-v4-flash", "deepseek-v4-pro", "hub-mock"]


def test_allowed_models_intersect_with_gateway():
    k = newapi.plan_key(["deepseek-v4-pro", "claude-sonnet"], AVAIL, "deepseek-v4-flash", 0, 0, 7.2)
    assert k["models"] == ["deepseek-v4-pro"] and k["model"] == "deepseek-v4-pro"  # 默认模型不在岗位包里时用第一个可用的


def test_default_model_preferred_when_allowed():
    k = newapi.plan_key(["deepseek-v4-pro", "deepseek-v4-flash"], AVAIL, "deepseek-v4-flash", 0, 0, 7.2)
    assert k["model"] == "deepseek-v4-flash" and k["models"] == ["deepseek-v4-pro", "deepseek-v4-flash"]


def test_stale_pack_models_fall_back_to_default_only():
    k = newapi.plan_key(["claude-sonnet", "qwen-local"], AVAIL, "deepseek-v4-flash", 0, 0, 7.2)  # 旧的演示模型名
    assert k["models"] == ["deepseek-v4-flash"] and k["model"] == "deepseek-v4-flash"


def test_monthly_budget_becomes_remaining_quota():
    # ¥72 / 月 = $10 = 5,000,000 额度；本月已用 1,000,000
    k = newapi.plan_key(AVAIL, AVAIL, "deepseek-v4-flash", 72, 1_000_000, 7.2)
    assert k["unlimited"] is False and k["remain_quota"] == 4_000_000
    assert newapi.plan_key(AVAIL, AVAIL, "deepseek-v4-flash", 72, 9_000_000, 7.2)["remain_quota"] == 0  # 超支不出现负数
    assert newapi.plan_key(AVAIL, AVAIL, "deepseek-v4-flash", 0, 9_000_000, 7.2)["unlimited"] is True  # 0 = 不限


def test_enroll_applies_limits_to_employee_key(monkeypatch):
    claims = {"owner": "o", "name": "u", "displayName": "U", "groups": ["o/ops"]}
    monkeypatch.setattr(agent_api, "_verify_agent_token", lambda auth: claims)
    monkeypatch.setattr(agent_api.policy, "resolve_pack", lambda org, user, dept: {
        "name": "运营", "skills": [], "tools": [], "max_action_level": "需确认", "model_mode": "中枢模型",
        "models": ["deepseek-v4-pro"], "monthly_quota": 72})
    monkeypatch.setattr(agent_api.db, "add_audit", lambda **e: None)
    monkeypatch.setattr(agent_api, "settings", dataclasses.replace(agent_api.settings, default_model="deepseek-v4-flash", usd_cny=7.2))
    applied = {}

    class FakeNewApi:
        configured = True

        def available_models(self):
            return AVAIL

        def month_used_quota(self, name):
            return 500_000

        def ensure_token(self, name, models=None, remain_quota=None, unlimited=True):
            applied.update(name=name, models=models, remain_quota=remain_quota, unlimited=unlimited)
            return "sk-test"
    monkeypatch.setattr(agent_api, "NewApi", FakeNewApi)
    r = client.post("/api/agent/enroll", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200 and r.json()["model"]["model"] == "deepseek-v4-pro"
    assert applied == {"name": "hub-o-u", "models": ["deepseek-v4-pro"], "remain_quota": 4_500_000, "unlimited": False}
