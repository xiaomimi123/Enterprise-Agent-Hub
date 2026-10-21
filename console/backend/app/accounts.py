"""账号状态检查：令牌签名有效不代表这个人还能用——被停用或删除的成员要立刻失去访问。

对每次受保护的请求按「组织 + 用户名」查一次 Casdoor 的 isForbidden / 是否存在，结果缓存 30 秒；
停用、启用、删除时在本进程内立即清缓存（MCP 服务与控制台是不同进程，最多 30 秒后生效）。
查询本身出错（Casdoor 暂时不可用）时放行，不让身份服务的抖动拖垮所有人；明确查到「已停用 / 不存在」才拒绝。
"""

from __future__ import annotations

import logging
import time

import httpx

from .config import settings

log = logging.getLogger("hub.accounts")
CACHE_SECONDS = 30
_cache: dict[tuple[str, str], tuple[float, bool]] = {}
_http: httpx.Client | None = None


def _client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(base_url=settings.casdoor_endpoint, timeout=3,
                             auth=(settings.casdoor_client_id, settings.casdoor_client_secret))
    return _http


def invalidate(org: str, name: str) -> None:
    _cache.pop((org, name), None)


def is_active(org: str, name: str) -> bool:
    if not settings.auth_enabled or not name:
        return True
    key = (org, name)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        body = _client().get("/api/get-user", params={"id": f"{org}/{name}"}).json()
        if body.get("status") != "ok":
            raise RuntimeError(body.get("msg"))
        u = body.get("data")
        active = bool(u) and not u.get("isForbidden") and not u.get("isDeleted")
    except Exception as e:  # noqa: BLE001 身份服务暂时不可用：放行，不缓存
        log.warning("查询账号状态失败，暂时放行 %s/%s：%s", org, name, e)
        return True
    _cache[key] = (time.time(), active)
    return active
