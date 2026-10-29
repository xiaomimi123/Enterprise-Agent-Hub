"""降级时留一条日志，但不刷屏。

「读不到就退回默认值」的写法本身没问题（页面不能因为一个辅助数据挂掉），问题是退回得悄无声息：
价格读不到时花费会悄悄按记录里的额度算，审计读不到时「最近活跃」悄悄退回登录时间，没人知道出过问题。
同一处的同一类失败，每 10 分钟最多记一条。"""

from __future__ import annotations

import logging
import time

_last: dict[str, float] = {}
EVERY_SECONDS = 600


def warn_throttled(log: logging.Logger, key: str, msg: str, *args, now: float | None = None) -> bool:
    """记一条 warning（带异常信息）；这个 key 在 EVERY_SECONDS 内记过就跳过。返回是否真的记了。"""
    t = time.monotonic() if now is None else now
    if t - _last.get(key, -EVERY_SECONDS * 2) < EVERY_SECONDS:
        return False
    _last[key] = t
    log.warning(msg, *args, exc_info=True)
    return True
