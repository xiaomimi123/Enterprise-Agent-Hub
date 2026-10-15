import pytest

from app import entitlements
from app.newapi import NewApi


class FakeNewApi(NewApi):
    def __init__(self, models, used_quota=0):
        self.base_url, self.headers = "http://x", {"Authorization": "t", "New-Api-User": "1"}
        self._models, self._used, self.updates = models, used_quota, []

    def enabled_models(self):
        return self._models

    def logs(self, days=30, **_):
        import time
        return [{"token_name": "hub-xinghe-u1", "quota": self._used, "created_at": int(time.time())}]

    def ensure_token(self, name):
        return {"id": 7, "name": name, "status": 1, "expired_time": -1}

    def token_key(self, token_id):
        return "sk-test"

    def _call(self, method, path, **kw):
        self.updates.append(kw.get("json"))


PACK = {"name": "小红书运营", "models": ["claude-sonnet", "hub-mock"], "monthly_quota": 300}


def setup_function():
    entitlements._models_cache = (0.0, [])


@pytest.fixture(autouse=True)
def _no_model_key_db(monkeypatch):
    """演示模式的测试没有数据库；发放 key 时的归属登记在这里一律跳过。"""
    monkeypatch.setattr(entitlements.db, "register_model_key", lambda *a, **k: None)


def test_action_policy_levels():
    assert "terminal" in entitlements.action_policy("只读")["disabled_toolsets"]
    assert "terminal" not in entitlements.action_policy("需确认")["disabled_toolsets"]
    assert "messaging" in entitlements.action_policy("需确认")["disabled_toolsets"]
    assert "messaging" not in entitlements.action_policy("需二次确认")["disabled_toolsets"]
    assert entitlements.action_policy("未知等级")["level"] == "未知等级"
    assert "terminal" in entitlements.action_policy("未知等级")["disabled_toolsets"]  # 未知等级按只读处理


def test_only_models_in_gateway_are_allowed():
    na = FakeNewApi(["hub-mock", "hub-mock-pro"])
    ent = entitlements.apply_model_limits("xinghe", "u1", PACK, na)
    assert ent["model"]["allowed"] == ["hub-mock"]
    assert na.updates[-1]["model_limits"] == "hub-mock" and na.updates[-1]["status"] == 1


def test_no_usable_model_disables_key():
    na = FakeNewApi(["hub-mock"])
    ent = entitlements.apply_model_limits("xinghe", "u1", {**PACK, "models": ["qwen-local"]}, na)
    assert ent["model"] is None and "没有配置" in ent["reason"]
    assert na.updates[-1]["status"] == 2


def test_quota_exhausted_marks_key():
    na = FakeNewApi(["hub-mock"], used_quota=10**9)
    ent = entitlements.apply_model_limits("xinghe", "u1", PACK, na)
    assert ent["quota"]["remaining_cny"] == 0 and ent["reason"] == "本月额度已用完"
    assert na.updates[-1]["status"] == 4 and na.updates[-1]["remain_quota"] == 0


def test_apply_registers_key_with_hub_base_url(monkeypatch):
    reg = []
    monkeypatch.setattr(entitlements.db, "register_model_key",
                        lambda key, org, user, display_name="", dept="", channel="官方 agent":
                        reg.append((key, org, user, display_name, dept)))
    ent = entitlements.apply_model_limits("xinghe", "u1", PACK, FakeNewApi(["hub-mock"]),
                                          display_name="林小运", dept="运营部")
    assert reg == [("sk-test", "xinghe", "u1", "林小运", "运营部")]
    # 模型地址指向中枢代理（审计链路），不再直连模型网关
    assert ent["model"]["base_url"] == entitlements.settings.public_url + "/v1"
