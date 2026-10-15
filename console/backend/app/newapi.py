"""New API（模型网关）客户端：给每个员工发一个专属 key，并读取按人统计的用量。

- 每个员工一个 key，名字固定为 hub-<组织>-<用户名>，New API 的用量日志按 key 名记录，由此实现「按人计量」
- 用管理员的系统访问令牌调用管理接口（请求头 Authorization + New-Api-User）
"""

from __future__ import annotations

import time

import httpx

from .config import settings


class NewApiError(RuntimeError):
    pass


QUOTA_PER_USD = 500000  # New API 的额度单位：500000 = 1 美元


def token_name(org: str, user_name: str) -> str:
    return f"hub-{org}-{user_name}"[:50]


def user_from_token_name(name: str, org: str) -> str | None:
    prefix = f"hub-{org}-"
    return name[len(prefix):] if name.startswith(prefix) else None


class NewApi:
    def __init__(self, base_url: str | None = None, access_token: str | None = None, user_id: str | None = None):
        self.base_url = (base_url or settings.newapi_endpoint).rstrip("/")
        self.headers = {"Authorization": access_token or settings.newapi_access_token,
                        "New-Api-User": str(user_id or settings.newapi_admin_id)}
        self.http = httpx.Client(base_url=self.base_url, headers=self.headers, timeout=15)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.headers["Authorization"] and self.headers["New-Api-User"])

    def _call(self, method: str, path: str, **kw) -> object:
        body = self.http.request(method, path, **kw).json()
        if not body.get("success"):
            raise NewApiError(f"New API {path} 失败：{body.get('message')}")
        return body.get("data")

    # ---- 员工 key ----
    def find_token(self, name: str) -> dict | None:
        data = self._call("GET", "/api/token/search", params={"keyword": name, "p": 1, "size": 100})
        items = data.get("items", data) if isinstance(data, dict) else data
        return next((t for t in items or [] if t.get("name") == name), None)

    def ensure_token(self, name: str) -> dict:
        """返回该员工的 key 记录（没有则创建，初始为禁用、零额度，由 set_limits 按岗位包放开）。"""
        tok = self.find_token(name)
        if tok is None:
            self._call("POST", "/api/token/", json={
                "name": name, "unlimited_quota": False, "remain_quota": 0, "expired_time": -1,
                "model_limits_enabled": True, "model_limits": "",
            })
            tok = self.find_token(name)
            if tok is None:
                raise NewApiError(f"创建 key {name} 后未找到")
        return tok

    def token_key(self, token_id: int) -> str:
        key = self._call("POST", f"/api/token/{token_id}/key")["key"]
        return key if key.startswith("sk-") else f"sk-{key}"

    def set_limits(self, token: dict, models: list[str], remain_quota: int) -> None:
        """限定 key 可用的模型和剩余额度。没有可用模型时禁用 key。"""
        # 没有可用模型 → 禁用；额度用完 → 标记「已耗尽」（模型网关给出额度用尽的提示）；否则启用
        status = 2 if not models else (1 if remain_quota > 0 else 4)
        self._call("PUT", "/api/token/", json={
            **{k: token.get(k) for k in ("id", "name", "expired_time", "allow_ips", "group", "cross_group_retry")},
            "status": status, "unlimited_quota": False, "remain_quota": max(0, remain_quota),
            "model_limits_enabled": True, "model_limits": ",".join(models),
        })

    def enabled_models(self) -> list[str]:
        return list(self._call("GET", "/api/channel/models_enabled") or [])

    # ---- 用量 ----
    def logs(self, days: int = 30, page_size: int = 100, max_pages: int = 50) -> list[dict]:
        """近 N 天的模型调用日志（type=2 为消费记录）。"""
        start = int(time.time()) - days * 86400
        out: list[dict] = []
        for p in range(1, max_pages + 1):
            data = self._call("GET", "/api/log/", params={"p": p, "page_size": page_size, "type": 2,
                                                          "start_timestamp": start})
            items = data.get("items", []) if isinstance(data, dict) else (data or [])
            out += items
            if len(items) < page_size:
                break
        return out
