"""本月花费 / 员工月额度按「当前配置的价格」重算，不用调用记录里可能虚高的额度（2026-10-21 价格没设好，一天记成 $847）。"""
from datetime import datetime

from app import newapi

QPU = newapi.QUOTA_PER_USD
PRICES = {"deepseek-v4-flash": (3.0, 3.0), "m2": (1.0, 4.0)}


def log(model, p, c, quota, token="hub-o-u", ts=None):
    return {"token_name": token, "model_name": model, "prompt_tokens": p, "completion_tokens": c, "quota": quota, "created_at": ts or datetime.now().timestamp()}


def test_repriced_quota_uses_input_and_output_price_not_the_stored_quota():
    inflated = log("deepseek-v4-flash", 1_000_000, 1_000_000, quota=int(150 * QPU))       # 记成了 $150
    assert newapi.NewApi.repriced_quota(inflated, PRICES) == 6 * QPU                       # 实际 2M token × $3 = $6
    assert newapi.NewApi.repriced_quota(log("m2", 2_000_000, 1_000_000, 0), PRICES) == (2 * 1 + 1 * 4) * QPU   # 输入输出分开计价


def test_repriced_quota_falls_back_to_stored_quota_when_model_has_no_price():
    assert newapi.NewApi.repriced_quota(log("unpriced-model", 5, 5, quota=1234), PRICES) == 1234
    assert newapi.NewApi.repriced_quota({"quota": 77}, PRICES) == 77                       # 没有 model_name
    assert newapi.NewApi.repriced_quota(log("deepseek-v4-flash", 0, 0, quota=999), PRICES) == 0   # 0 token 就是 0 花费


def test_month_used_quota_is_repriced_and_still_ignores_other_people_and_other_months(monkeypatch):
    now = datetime.now().timestamp()
    logs = [log("deepseek-v4-flash", 1_000_000, 0, quota=int(75 * QPU), token="hub-o-u"),                 # 虚高：$75 → 重算 $3
            log("deepseek-v4-flash", 1_000_000, 0, quota=int(75 * QPU), token="hub-o-u~tr-aaaa"),          # 会话 key 也算他的
            log("deepseek-v4-flash", 1_000_000, 0, quota=int(75 * QPU), token="hub-o-other"),              # 别人
            log("deepseek-v4-flash", 1_000_000, 0, quota=int(75 * QPU), token="hub-o-u", ts=now - 90 * 86400)]  # 上个月
    na = newapi.NewApi("http://x", "t", "1")
    monkeypatch.setattr(na, "logs", lambda days=31, **k: logs)
    monkeypatch.setattr(na, "get_pricing", lambda models: [{"model": "deepseek-v4-flash", "configured": True, "input_per_m": 3.0, "output_per_m": 3.0}])
    assert na.month_used_quota("hub-o-u") == 6 * QPU


def test_price_table_only_keeps_configured_models_and_never_raises(monkeypatch):
    na = newapi.NewApi("http://x", "t", "1")
    monkeypatch.setattr(na, "get_pricing", lambda models: [{"model": "a", "configured": True, "input_per_m": 1, "output_per_m": 2}, {"model": "b", "configured": False, "input_per_m": 75, "output_per_m": 75}])
    assert na.price_table(["a", "b", None, "a"]) == {"a": (1.0, 2.0)}
    assert na.price_table([]) == {}                                                         # 没有模型：不去读价格

    def boom(models):
        raise newapi.NewApiError("网关不可用")
    monkeypatch.setattr(na, "get_pricing", boom)
    assert na.price_table(["a"]) == {}                                                      # 读不到价格：返回空，退回记录里的额度
