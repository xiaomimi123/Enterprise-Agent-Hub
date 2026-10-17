"""员工端在线状态：接入器每分钟报到一次（带 agent 名称、版本、系统），官方 agent 调用中枢工具时也会刷新。

5 分钟内有信号算「在线」，报到过但超时算「离线」，从没出现过算「未安装」。
"""

from __future__ import annotations

from datetime import datetime

ONLINE_MINUTES = 5


def member_agent(row: dict | None, now: datetime) -> dict:
    """把在线记录转成控制台成员列表的三个字段。"""
    if not row:
        return {"agent_status": "未安装", "agent_version": "", "os": ""}
    online = (now - row["last_seen"]).total_seconds() < ONLINE_MINUTES * 60
    where = " · ".join(x for x in (row.get("client"), row.get("os")) if x) or "官方 agent"
    return {"agent_status": "在线" if online else "离线", "agent_version": row.get("version") or "", "os": where}
