"""岗位包 → 员工端的实际权益。

岗位包里配置的「可用模型、每人月额度、本机动作上限」在这里落地：
- 模型与额度：写到员工专属的 New API key 上（模型白名单 + 本月剩余额度），超出由模型网关直接拒绝
- 本机动作上限：翻译成 Hermes 的配置（关闭哪些工具组、危险命令是否必须确认、写文件限定在工作区）

调用时机：员工端领取配置时、控制台修改岗位包或成员分配时、GPU 调度服务每 10 分钟巡检一次（跨月自动恢复额度）。
"""

from __future__ import annotations

import time
from datetime import datetime

from . import db
from .config import settings
from .newapi import QUOTA_PER_USD, NewApi, NewApiError, token_name

# 本机动作上限 → Hermes 配置。工具组名称见 Hermes 文档 toolsets-reference
ACTION_POLICIES = {
    "只读": {
        "disabled_toolsets": ["terminal", "file", "code_execution", "browser", "computer_use",
                              "messaging", "cronjob", "delegation"],
        "approvals_mode": "manual", "write_sandbox": True,
        "summary": "只能对话、查知识、用技能，不能在电脑上执行命令或写文件",
    },
    "需确认": {
        "disabled_toolsets": ["messaging", "computer_use"],
        "approvals_mode": "manual", "write_sandbox": True,
        "summary": "可以执行命令和写文件（只能写在中枢工作区），危险命令须确认；不能对外发消息",
    },
    "需二次确认": {
        "disabled_toolsets": ["computer_use"],
        "approvals_mode": "manual", "write_sandbox": True,
        "summary": "可以执行命令、写文件（只能写在中枢工作区）、对外发消息，危险动作须确认",
    },
}

_models_cache: tuple[float, list[str]] = (0.0, [])


def action_policy(level: str) -> dict:
    return {"level": level, **ACTION_POLICIES.get(level, ACTION_POLICIES["只读"])}


def available_models(na: NewApi) -> list[str]:
    """模型网关里实际可用的模型（缓存 60 秒）。"""
    global _models_cache
    if time.time() - _models_cache[0] > 60:
        _models_cache = (time.time(), na.enabled_models())
    return _models_cache[1]


def month_used_quota(na: NewApi, name: str) -> int:
    """本月该 key 已消耗的额度（New API 单位）。"""
    start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    days = int((time.time() - start) // 86400) + 1
    return sum(int(log.get("quota") or 0) for log in na.logs(days=days)
               if log.get("token_name") == name and (log.get("created_at") or 0) >= start)


def apply_model_limits(org: str, user_name: str, pack: dict, na: NewApi | None = None) -> dict:
    """按岗位包设置员工 key 的模型白名单和本月剩余额度，返回下发给员工端的模型信息。"""
    na = na or NewApi()
    if not na.configured:
        return {"model": None, "reason": "中枢未配置模型网关"}
    name = token_name(org, user_name)
    allowed = [m for m in pack.get("models", []) if m in available_models(na)]
    budget = int(pack.get("monthly_quota", 0) / settings.usd_cny * QUOTA_PER_USD)
    used = month_used_quota(na, name)
    token = na.ensure_token(name)
    na.set_limits(token, allowed, budget - used)
    quota = {"monthly_cny": pack.get("monthly_quota", 0),
             "used_cny": round(used / QUOTA_PER_USD * settings.usd_cny, 2),
             "remaining_cny": round(max(0, budget - used) / QUOTA_PER_USD * settings.usd_cny, 2)}
    if not allowed:
        return {"model": None, "quota": quota,
                "reason": f"岗位包「{pack['name']}」没有配置模型网关里可用的模型，请联系管理员"}
    default = settings.default_model if settings.default_model in allowed else allowed[0]
    return {"model": {"base_url": f"{settings.newapi_public_url}/v1", "api_key": na.token_key(token["id"]),
                      "model": default, "allowed": allowed},
            "quota": quota,
            "reason": "本月额度已用完" if budget - used <= 0 else ""}


def resync_all(org: str) -> int:
    """给所有用过员工端的成员重新下发模型限制与额度（巡检用，跨月自动恢复额度）。"""
    from . import policy  # 避免循环导入

    na = NewApi()
    if not na.configured:
        return 0
    n = 0
    for p in db.agent_presence(org):
        pack = policy.resolve_pack(org, p["user_name"], p["dept"])
        try:
            apply_model_limits(org, p["user_name"], pack, na)
            n += 1
        except NewApiError:
            continue
    return n
