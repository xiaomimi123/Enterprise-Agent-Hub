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


def token_name(org: str, user_name: str) -> str:
    return f"hub-{org}-{user_name}"[:50]


QUOTA_PER_USD = 500000  # New API 的额度单位：500000 = 1 美元


def plan_key(pack_models: list[str], available: list[str], default_model: str, monthly_cny: float,
             used_month: int, usd_cny: float) -> dict:
    """员工 key 应该是什么样：能用哪些模型、默认哪个、本月还剩多少额度。

    - 可用模型 = 岗位包勾选的 ∩ 模型网关里真实存在的；交集为空（如岗位包还是旧的演示模型名）时只给默认模型
    - 每人月模型额度（人民币）换算成额度，减去本月已用，不出现负数；0 表示不限
    """
    allowed = [m for m in pack_models if m in available]
    if not allowed and default_model in available:
        allowed = [default_model]
    model = default_model if default_model in allowed else (allowed[0] if allowed else None)
    if monthly_cny and monthly_cny > 0:
        budget = round(monthly_cny / usd_cny * QUOTA_PER_USD)
        return {"model": model, "models": allowed, "unlimited": False, "remain_quota": max(0, budget - used_month)}
    return {"model": model, "models": allowed, "unlimited": True, "remain_quota": 0}


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

    def ensure_token(self, name: str, models: list[str] | None = None, remain_quota: int | None = None,
                     unlimited: bool = True) -> str:
        """返回该员工的 key（没有则创建）。传了 models / 额度时，按岗位包更新 key 的模型限制和剩余额度。"""
        tok = self.find_token(name)
        if tok is None:
            self._call("POST", "/api/token/", json={
                "name": name, "unlimited_quota": True, "remain_quota": 0, "expired_time": -1,
            })
            tok = self.find_token(name)
            if tok is None:
                raise NewApiError(f"创建 key {name} 后未找到")
        if models is not None or not unlimited:
            want = {"model_limits_enabled": bool(models), "model_limits": ",".join(models or []),
                    "unlimited_quota": unlimited, "remain_quota": 0 if unlimited else int(remain_quota or 0)}
            if any(tok.get(k) != v for k, v in want.items()):
                self._call("PUT", "/api/token/", json={**tok, **want})
        key = self._call("POST", f"/api/token/{tok['id']}/key")["key"]
        return key if key.startswith("sk-") else f"sk-{key}"

    # ---- 模型与用量 ----
    def available_models(self) -> list[str]:
        """模型网关里启用的渠道提供的全部模型（去重，保持顺序）。"""
        data = self._call("GET", "/api/channel/", params={"p": 0, "page_size": 100})
        items = data.get("items", data) if isinstance(data, dict) else (data or [])
        out: list[str] = []
        for c in items:
            if c.get("status") != 1:
                continue
            for m in (c.get("models") or "").split(","):
                if m.strip() and m.strip() not in out:
                    out.append(m.strip())
        return out

    def month_used_quota(self, name: str) -> int:
        """这个 key 本月已用的额度（New API 的累计用量不分月，按调用日志算）。"""
        start = time.localtime()
        month_start = time.mktime((start.tm_year, start.tm_mon, 1, 0, 0, 0, 0, 0, -1))
        return sum(int(log.get("quota") or 0) for log in self.logs(days=31)
                   if log.get("token_name") == name and (log.get("created_at") or 0) >= month_start)

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
