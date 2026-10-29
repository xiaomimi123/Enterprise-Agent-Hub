"""员工端在线状态。三种信号，任何一种 5 分钟内出现过就算「在线」，报到过但超时算「离线」，从没出现过算「未安装」：

1. 接入器每分钟报到一次（带 agent 名称、版本、系统）——只有 agent 本身开着时才有；
2. 官方 agent 调用中枢工具时刷新；
3. **模型网关里的调用**：员工用中枢模型就会经过网关（不管是工作台、WorkBuddy 还是 CodeBuddy），这里每 20 秒读一次最新的调用记录。
   只看「用中枢模型」的人——用自带模型的（如 WorkBuddy 桌面里直接聊天）不经过网关，靠 1、2 补上。
工作台开着时也会报到（工作台 0.8.25 起，见 xhs-workbench）。
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

ONLINE_MINUTES = 5
GATEWAY_POLL_SECONDS = 20     # 读网关日志的最短间隔（有人看总览 / 成员 / 应用健康时才读）
GATEWAY_WINDOW_SECONDS = 600  # 每次读最近 10 分钟：覆盖 5 分钟的在线窗口并留余量；重复写同一时间点无害（只往后推）
log = logging.getLogger("hub.presence")
_gateway_polled_at = 0.0


def last_call_by_user(logs: list[dict], org: str) -> dict[str, datetime]:
    """从网关的消费记录里取每个员工最近一次调用的时间（key 名里带着员工账号，会话专属 key 也能还原）。"""
    from .newapi import user_from_token_name
    out: dict[str, datetime] = {}
    for item in logs:
        user = user_from_token_name(str(item.get("token_name") or ""), org)
        created = int(item.get("created_at") or 0)
        if not user or created <= 0:
            continue
        ts = datetime.fromtimestamp(created, tz=timezone.utc)
        if user not in out or ts > out[user]:
            out[user] = ts
    return out


def sync_from_gateway(org: str, client=None, touch=None, now=None) -> int:
    """把模型网关里最近有调用的员工记为在线。返回更新了几个人；网关不可用 / 没配置时什么都不做（不影响页面）。
    20 秒内重复调用直接返回 0，所以放在每次读在线状态之前很便宜。"""
    global _gateway_polled_at
    t = now if now is not None else time.time()
    if t - _gateway_polled_at < GATEWAY_POLL_SECONDS:
        return 0
    _gateway_polled_at = t
    try:
        if client is None:
            from .newapi import NewApi
            client = NewApi()
        if not client.configured:
            return 0
        users = last_call_by_user(client.recent_logs(int(t) - GATEWAY_WINDOW_SECONDS), org)
        if touch is None:
            from . import db
            touch = db.touch_presence_at
        for user, ts in users.items():
            touch(org, user, ts)
        return len(users)
    except Exception as e:  # noqa: BLE001 网关暂时不可用、数据库出错都不能影响页面
        log.warning("读取模型网关的调用记录失败（在线状态只靠心跳和工具调用）：%s", e)
        return 0


def daily_ops(online: dict[str, int], denied: dict[str, int], today: date, days: int = 14) -> list[dict]:
    """总览的近 N 天历史：每天的在线人数和被拦截次数，没有记录的天补 0，按日期从早到晚。"""
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        out.append({"date": d, "online": online.get(d, 0), "denied": denied.get(d, 0)})
    return out


def _as_dt(v) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def latest_activity(signin, seen, event) -> str | None:
    """成员列表的「最近活跃」：Casdoor 上次密码登录、在线记录、审计里最近一条事件三者取最晚的。

    只用 Casdoor 的 lastSigninTime 会错：员工接入后用令牌静默续期，不会再输入密码登录，这个时间永远停在首次登录那天，
    而同一个人今天还在用工作台（2026-10-29 成员页写「8 天前」，实时活动里却有 1 小时前的记录）。"""
    cands = [d for d in (_as_dt(signin), _as_dt(seen), _as_dt(event)) if d]
    return max(cands).isoformat() if cands else None


def member_agent(row: dict | None, now: datetime) -> dict:
    """把在线记录转成控制台成员列表的三个字段。"""
    if not row:
        return {"agent_status": "未安装", "agent_version": "", "os": ""}
    online = (now - row["last_seen"]).total_seconds() < ONLINE_MINUTES * 60
    where = " · ".join(x for x in (row.get("client"), row.get("os")) if x) or "官方 agent"
    return {"agent_status": "在线" if online else "离线", "agent_version": row.get("version") or "", "os": where}
