"""New API（模型网关）客户端：给每个员工发一个专属 key，并读取按人统计的用量。

- 每个员工一个 key，名字固定为 hub-<组织>-<用户名>，New API 的用量日志按 key 名记录，由此实现「按人计量」
- 用管理员的系统访问令牌调用管理接口（请求头 Authorization + New-Api-User）
"""

from __future__ import annotations

import json
import time

import httpx

from .config import settings


class NewApiError(RuntimeError):
    pass


# ---- 模型价格（New API 的 ModelRatio / CompletionRatio 选项）----
# 倍率 1 = 每百万输入 token 2 美元；输出价 = 输入价 × CompletionRatio。没有设置倍率的模型，New API 按默认 37.5 计费（= 每百万 75 美元），
# 费用会虚高，额度很快被「花光」。
USD_PER_M_AT_RATIO_1 = 2.0
DEFAULT_MODEL_RATIO = 37.5
MAX_PRICE_PER_M = 10000.0


def token_name(org: str, user_name: str) -> str:
    return f"hub-{org}-{user_name}"[:50]


_TOKEN_CACHE: dict[str, tuple[float, dict[str, dict]]] = {}
TOKEN_CACHE_SECONDS = 30
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


SESSION_SEP = "~"
SESSION_KEY_TTL = 3 * 86400  # 会话 key 3 天后过期，下次领取配置时顺手清理


def session_token_name(org: str, user_name: str, trace_id: str) -> str:
    """会话专属 key 的名字：<基础名>~<追踪 ID>。

    New API 不会记录客户端传来的任何自定义信息（请求头、user、metadata 都实测过），但一定会记 key 的名字，
    所以把追踪 ID 编进 key 名，调用日志里的 token_name 就直接带着它，归属不再靠时间窗估算。
    追踪 ID 来自请求头，不可信：只保留字母数字和 - _，并限制长度。
    """
    safe = "".join(c for c in trace_id if c.isalnum() or c in "-_")[:20] or "none"
    suffix = f"{SESSION_SEP}{safe}"
    return token_name(org, user_name)[: 50 - len(suffix)] + suffix


def trace_from_token_name(name: str) -> str | None:
    return name.split(SESSION_SEP, 1)[1] if SESSION_SEP in name else None


def user_from_token_name(name: str, org: str) -> str | None:
    prefix = f"hub-{org}-"
    return name[len(prefix):].split(SESSION_SEP, 1)[0] if name.startswith(prefix) else None


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
        r = self.http.request(method, path, **kw)
        # 被限流（429）时等一下再试两次：员工同时同步、CodeBuddy 频繁重连时会撞上 New API 管理接口的频率上限
        for wait in (1.0, 2.5):
            if r.status_code != 429:
                break
            try:
                wait = min(float(r.headers.get("Retry-After") or wait), 5.0)
            except ValueError:
                pass
            time.sleep(wait)
            r = self.http.request(method, path, **kw)
        try:
            body = r.json()
        except ValueError:  # 限流（HTTP 429、空响应）或网关错误页
            raise NewApiError(f"New API {path} 返回 HTTP {r.status_code}（非 JSON 响应，可能被限流）") from None
        if not body.get("success"):
            raise NewApiError(f"New API {path} 失败：{body.get('message')}")
        return body.get("data")

    # ---- 员工 key ----
    def _token_index(self, refresh: bool = False) -> dict[str, dict]:
        """全部员工 key 按名字建的索引，缓存 30 秒（跨实例共享，每次领取配置都会新建客户端）。

        不用 /api/token/search：New API 对它做全局限流（约 10 次 / 分钟，而我们所有请求共用一个管理员身份），
        几个人同时同步就会被限住。列表接口没有这个限制，且带总数可翻页。
        """
        hit = _TOKEN_CACHE.get(self.base_url)
        if hit and not refresh and time.time() - hit[0] < TOKEN_CACHE_SECONDS:
            return hit[1]
        index: dict[str, dict] = {}
        page = 0
        while True:
            data = self._call("GET", "/api/token/", params={"p": page, "size": 100})
            items = data.get("items", data) if isinstance(data, dict) else (data or [])
            index.update({t["name"]: t for t in items if t.get("name")})
            if len(items) < 100:
                break
            page += 1
        _TOKEN_CACHE[self.base_url] = (time.time(), index)
        return index

    def find_token(self, name: str) -> dict | None:
        found = self._token_index().get(name)
        # 没命中时强制刷新一次再确认，避免别的进程刚创建的 key 被当成不存在而重复创建
        return found or self._token_index(refresh=True).get(name)

    def ensure_token(self, name: str, models: list[str] | None = None, remain_quota: int | None = None,
                     unlimited: bool = True, expires_in: int | None = None) -> str:
        """返回该员工的 key（没有则创建）。传了 models / 额度时，按岗位包更新 key 的模型限制和剩余额度；
        expires_in 是新建时的有效期（秒），已存在的 key 不改有效期。"""
        tok = self.find_token(name)
        if tok is None:
            self._call("POST", "/api/token/", json={
                "name": name, "unlimited_quota": True, "remain_quota": 0,
                "expired_time": int(time.time()) + expires_in if expires_in else -1,
            })
            tok = self._token_index(refresh=True).get(name)
            if tok is None:
                raise NewApiError(f"创建 key {name} 后未找到")
        if models is not None or not unlimited:
            want = {"model_limits_enabled": bool(models), "model_limits": ",".join(models or []),
                    "unlimited_quota": unlimited, "remain_quota": 0 if unlimited else int(remain_quota or 0)}
            if any(tok.get(k) != v for k, v in want.items()):
                self._call("PUT", "/api/token/", json={**tok, **want})
        key = self._call("POST", f"/api/token/{tok['id']}/key")["key"]
        return key if key.startswith("sk-") else f"sk-{key}"

    # ---- 渠道（上游模型）管理 ----
    # 以下字段和响应形状均已对真实 New API 实测：列表接口永远不返回 key（key 是空串），所以中枢把「后四位提示」
    # 存在渠道的 remark 字段里；创建接口只回 success、不回 id，需要再按名字查；更新（PUT）可以只传要改的字段，
    # 不传 key 就是不改；状态 1 = 启用，2 = 手动停用。
    def list_channels(self) -> list[dict]:
        items: list[dict] = []
        page = 0
        while True:
            data = self._call("GET", "/api/channel/", params={"p": page, "page_size": 100})
            batch = data.get("items", data) if isinstance(data, dict) else (data or [])
            items += batch
            if len(batch) < 100:
                return items
            page += 1

    def fetch_models(self, base_url: str, key: str) -> list[str]:
        """让 New API 去上游拉模型清单（OpenAI 兼容的 GET {base_url}/v1/models）。"""
        return list(self._call("POST", "/api/channel/fetch_models", json={"base_url": base_url, "type": 1, "key": key}) or [])

    def create_channel(self, name: str, base_url: str, key: str, models: list[str], remark: str = "") -> int:
        self._call("POST", "/api/channel/", json={"mode": "single", "channel": {
            "name": name, "type": 1, "key": key, "base_url": base_url, "models": ",".join(models),
            "group": "default", "status": 1, "remark": remark}})
        found = next((c for c in self.list_channels() if c["name"] == name), None)
        if found is None:
            raise NewApiError(f"创建渠道 {name} 后未找到")
        return found["id"]

    def update_channel(self, channel_id: int, **fields) -> None:
        self._call("PUT", "/api/channel/", json={"id": channel_id, **fields})

    def delete_channel(self, channel_id: int) -> None:
        self._call("DELETE", f"/api/channel/{channel_id}")

    # ---- 模型与用量 ----
    # ---- 模型价格 ----
    def _price_options(self) -> tuple[dict, dict]:
        opts = {o.get("key"): o.get("value") for o in (self._call("GET", "/api/option/") or [])}
        def load(key: str) -> dict:
            try:
                data = json.loads(opts.get(key) or "{}")
            except ValueError:
                raise NewApiError(f"New API 的 {key} 选项不是合法 JSON，请先在 New API 后台修复") from None
            return data if isinstance(data, dict) else {}
        return load("ModelRatio"), load("CompletionRatio")

    def _put_option(self, key: str, value: dict) -> None:
        self._call("PUT", "/api/option/", json={"key": key, "value": json.dumps(value, ensure_ascii=False)})

    @staticmethod
    def _price_row(model: str, ratios: dict, completions: dict) -> dict:
        ratio = ratios.get(model)
        configured = ratio is not None
        r = float(ratio) if configured else DEFAULT_MODEL_RATIO
        c = float(completions.get(model) or 1) if configured else 1.0
        return {"model": model, "configured": configured, "input_per_m": round(r * USD_PER_M_AT_RATIO_1, 6),
                "output_per_m": round(r * c * USD_PER_M_AT_RATIO_1, 6)}

    def get_pricing(self, models: list[str]) -> list[dict]:
        """这些模型当前的价格（美元 / 百万 token）；configured=false 表示没设置，正按默认的虚高价格计费。"""
        ratios, completions = self._price_options()
        return [self._price_row(m, ratios, completions) for m in models]

    def set_pricing(self, model: str, input_per_m: float, output_per_m: float | None = None) -> dict:
        model = (model or "").strip()
        if not model or len(model) > 100:
            raise NewApiError("模型名不合法")
        out = input_per_m if output_per_m is None else output_per_m
        for label, v in (("输入价", input_per_m), ("输出价", out)):
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 < v <= MAX_PRICE_PER_M):
                raise NewApiError(f"{label}必须大于 0 且不超过每百万 token {MAX_PRICE_PER_M:g} 美元")
        ratios, completions = self._price_options()
        ratios[model] = round(input_per_m / USD_PER_M_AT_RATIO_1, 6)
        completions[model] = round(out / input_per_m, 6)
        self._put_option("ModelRatio", ratios)
        self._put_option("CompletionRatio", completions)
        return self._price_row(model, ratios, completions)

    def clear_pricing(self, model: str) -> bool:
        """去掉这个模型的自定义价格（恢复 New API 的默认）。本来就没设置返回 False。"""
        ratios, completions = self._price_options()
        if model not in ratios and model not in completions:
            return False
        ratios.pop(model, None)
        completions.pop(model, None)
        self._put_option("ModelRatio", ratios)
        self._put_option("CompletionRatio", completions)
        return True

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
        """这个人本月已用的额度：基础 key 加上他所有会话 key 的合计（New API 的累计用量不分月，按调用日志算）。"""
        start = time.localtime()
        month_start = time.mktime((start.tm_year, start.tm_mon, 1, 0, 0, 0, 0, 0, -1))
        mine = (name, )
        return sum(int(log.get("quota") or 0) for log in self.logs(days=31)
                   if (log.get("token_name") or "").split(SESSION_SEP, 1)[0] in mine
                   and (log.get("created_at") or 0) >= month_start)

    def purge_expired_sessions(self, base_name: str) -> int:
        """删除这个人已过期的会话 key，返回删除个数。基础 key 永不动。
        删除不影响历史归属：调用日志里记的是 key 的名字，不是 key 的 ID。"""
        index = self._token_index()
        now = int(time.time())
        n = 0
        for name, t in list(index.items()):
            exp = t.get("expired_time") or -1
            if name.startswith(base_name + SESSION_SEP) and exp != -1 and exp < now:
                self.http.delete(f"/api/token/{t['id']}")
                index.pop(name, None)
                n += 1
        return n

    def delete_tokens_of(self, org: str, user_name: str) -> int:
        """删除这个人的全部 key（基础 key 和会话 key），返回个数。成员被停用或删除时调用。
        历史调用日志记的是 key 的名字，删除不影响归属；重新启用后下次领取配置会自动新建。"""
        index = self._token_index(refresh=True)
        n = 0
        for name, t in list(index.items()):
            if user_from_token_name(name, org) == user_name:
                self.http.delete(f"/api/token/{t['id']}")
                index.pop(name, None)
                n += 1
        return n

    def recent_logs(self, since: int, page_size: int = 100, max_pages: int = 3) -> list[dict]:
        """最近的消费记录（type=2），只取 since（秒级时间戳）之后的最新几页；给「谁在线」用，比 logs() 轻得多。"""
        out: list[dict] = []
        for p in range(1, max_pages + 1):
            data = self._call("GET", "/api/log/", params={"p": p, "page_size": page_size, "type": 2, "start_timestamp": int(since)})
            items = data.get("items", []) if isinstance(data, dict) else (data or [])
            out += items
            if len(items) < page_size:
                break
        return out

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
