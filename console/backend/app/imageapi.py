"""第三方出图 API：配置（存数据库、密钥加密）与 apimart 风格的异步客户端。

- 出图通道开关 `image.route`：`gpu`（本机 ComfyUI，默认）或 `api`（第三方）；出图 API 列表 `image.providers`
- apimart 的调用方式是「提交 → 任务号 → 轮询」：POST {地址}/v1/images/generations 返回 data[0].task_id，
  再 GET {地址}/v1/tasks/{任务号}，完成时图片地址在 data.result.images[].url[]。字段来自 apimart 公开示例，
  解析刻意宽松（data 可以是对象或数组、url 可以是字符串或数组），并允许每个出图 API 配置额外参数（如 resolution）
- 密钥只加密落库，接口只回后四位；所有错误信息过滤掉密钥
"""

from __future__ import annotations

import math
import time
import uuid

import httpx

from . import secretbox, settings_store


class ImageApiError(Exception):
    """配置不合法或第三方出错，消息可以直接给管理员看（不含密钥）。"""


ROUTE_KEY, PROVIDERS_KEY = "image.route", "image.providers"
POLL_INTERVAL = 3.0


def _normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")) or len(url) < 9:
        raise ImageApiError("地址必须以 http:// 或 https:// 开头")
    return url[:-3].rstrip("/") if url.endswith("/v1") else url


def _scrub(msg: str, key: str) -> str:
    return msg.replace(key, "••••") if key else msg


def _ratio(width: int, height: int) -> str:
    g = math.gcd(width, height) or 1
    return f"{width // g}:{height // g}"


class ApimartClient:
    def __init__(self, base_url: str, key: str, model: str, params: dict | None = None,
                 client: httpx.Client | None = None):
        self.base_url, self.key, self.model, self.params = base_url.rstrip("/"), key, model, params or {}
        self.http = client or httpx.Client(timeout=30, follow_redirects=True)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            r = self.http.request(method, url, headers={"Authorization": f"Bearer {self.key}"}, **kw)
        except httpx.HTTPError as e:
            raise ImageApiError(_scrub(f"连接出图 API 失败：{e}", self.key)) from None
        if r.status_code >= 400:
            raise ImageApiError(_scrub(f"出图 API 返回 HTTP {r.status_code}：{r.text[:200]}", self.key))
        return r

    @staticmethod
    def _data(r: httpx.Response) -> dict:
        try:
            body = r.json()
        except ValueError:
            raise ImageApiError("出图 API 返回的不是 JSON") from None
        data = body.get("data", body) if isinstance(body, dict) else body
        return (data[0] if data else {}) if isinstance(data, list) else (data or {})

    def submit(self, prompt: str, width: int, height: int, count: int) -> str:
        body = {"model": self.model, "prompt": prompt, "size": _ratio(width, height), "n": count, **self.params}
        d = self._data(self._request("POST", f"{self.base_url}/v1/images/generations", json=body))
        task = d.get("task_id") or d.get("id")
        if not task:
            raise ImageApiError("出图 API 没有返回任务号")
        return str(task)

    def poll(self, task_id: str) -> tuple[str, list[str]]:
        d = self._data(self._request("GET", f"{self.base_url}/v1/tasks/{task_id}"))
        status = str(d.get("status") or "").lower()
        if status in ("failed", "error", "cancelled", "canceled"):
            return "failed", []
        if status not in ("completed", "succeeded", "success"):
            return "running", []
        urls: list[str] = []
        for img in (d.get("result") or {}).get("images") or []:
            u = img.get("url") if isinstance(img, dict) else img
            urls += [u] if isinstance(u, str) else list(u or [])
        return "done", urls

    def download(self, url: str) -> bytes:
        try:
            r = self.http.get(url)
        except httpx.HTTPError as e:
            raise ImageApiError(_scrub(f"下载图片失败：{e}", self.key)) from None
        if r.status_code >= 400:
            raise ImageApiError(f"下载图片失败：HTTP {r.status_code}")
        return r.content

    def test(self) -> dict:
        """最小尺寸实际出一张，返回 {ok, seconds, error}；不计入员工任务。"""
        start = time.time()
        try:
            task = self.submit("a small red circle on white background", 512, 512, 1)
            while time.time() - start < 120:
                state, urls = self.poll(task)
                if state == "failed":
                    return {"ok": False, "seconds": round(time.time() - start, 1), "error": "第三方返回失败"}
                if state == "done":
                    if not urls:
                        return {"ok": False, "seconds": round(time.time() - start, 1), "error": "完成了但没有图片"}
                    self.download(urls[0])
                    return {"ok": True, "seconds": round(time.time() - start, 1), "error": ""}
                time.sleep(POLL_INTERVAL)
            return {"ok": False, "seconds": 120.0, "error": "120 秒内没有出图"}
        except ImageApiError as e:
            return {"ok": False, "seconds": round(time.time() - start, 1), "error": str(e)}


# ---- 配置 ----

def _raw() -> list[dict]:
    return settings_store.get(PROVIDERS_KEY, []) or []


def _view(p: dict) -> dict:
    return {"id": p["id"], "name": p["name"], "kind": p.get("kind", "apimart"), "base_url": p["base_url"],
            "model": p["model"], "params": p.get("params") or {}, "enabled": bool(p.get("enabled", True)),
            "key_hint": p.get("key_hint", "")}


def list_providers() -> list[dict]:
    return [_view(p) for p in _raw()]


def get_route() -> str:
    try:
        return settings_store.get(ROUTE_KEY, "gpu") or "gpu"
    except RuntimeError:  # 没有数据库（演示模式）或数据库暂时不可用：一律走本机 GPU，不影响出图
        return "gpu"


def default_provider() -> dict | None:
    """第一个启用的出图 API（不看通道开关）：排队中的 API 任务按它派发，切回本机 GPU 也不影响已经提交的任务。"""
    return next((_view(p) for p in _raw() if p.get("enabled", True)), None)


def active_provider() -> dict | None:
    """当前生效的出图 API（含解密后的密钥，只在内部调用时用）；通道不是 api 或没有可用的出图 API 返回 None。"""
    if get_route() != "api":
        return None
    p = next((p for p in _raw() if p.get("enabled", True)), None)
    if p is None:
        return None
    return {**_view(p), "key": secretbox.decrypt(p["key_enc"])}


def client_for(provider: dict) -> ApimartClient:
    return ApimartClient(provider["base_url"], provider["key"], provider["model"], provider.get("params"))


def add_provider(name: str, base_url: str, model: str, key: str, params: dict | None = None) -> dict:
    name, model, key = (name or "").strip(), (model or "").strip(), (key or "").strip()
    if not name:
        raise ImageApiError("请填写名称")
    if not model:
        raise ImageApiError("请填写模型名")
    if not key:
        raise ImageApiError("请填写密钥")
    url = _normalize_url(base_url)
    p = {"id": uuid.uuid4().hex[:8], "name": name, "kind": "apimart", "base_url": url, "model": model,
         "params": params or {}, "enabled": True, "key_enc": secretbox.encrypt(key), "key_hint": secretbox.mask_secret(key)}
    settings_store.put(PROVIDERS_KEY, _raw() + [p])
    return _view(p)


def patch_provider(provider_id: str, *, name: str | None = None, base_url: str | None = None, model: str | None = None,
                   key: str | None = None, params: dict | None = None, enabled: bool | None = None) -> dict | None:
    items = _raw()
    p = next((x for x in items if x["id"] == provider_id), None)
    if p is None:
        return None
    if name is not None:
        if not name.strip():
            raise ImageApiError("请填写名称")
        p["name"] = name.strip()
    if base_url is not None:
        p["base_url"] = _normalize_url(base_url)
    if model is not None:
        if not model.strip():
            raise ImageApiError("请填写模型名")
        p["model"] = model.strip()
    if params is not None:
        p["params"] = params
    if enabled is not None:
        p["enabled"] = enabled
    if (key or "").strip():
        p["key_enc"], p["key_hint"] = secretbox.encrypt(key.strip()), secretbox.mask_secret(key.strip())
    settings_store.put(PROVIDERS_KEY, items)
    _fallback_route(items)
    return _view(p)


def remove_provider(provider_id: str) -> bool:
    items = _raw()
    kept = [p for p in items if p["id"] != provider_id]
    if len(kept) == len(items):
        return False
    settings_store.put(PROVIDERS_KEY, kept)
    _fallback_route(kept)
    return True


def _fallback_route(items: list[dict]) -> None:
    """没有可用的出图 API 时，通道自动退回本机 GPU，不让新任务提交到一个不存在的通道。"""
    if get_route() == "api" and not any(p.get("enabled", True) for p in items):
        settings_store.put(ROUTE_KEY, "gpu")


def set_route(route: str) -> str:
    if route not in ("gpu", "api"):
        raise ImageApiError("通道只能是 gpu 或 api")
    if route == "api" and not any(p.get("enabled", True) for p in _raw()):
        raise ImageApiError("没有可用的出图 API，请先添加并启用一个")
    settings_store.put(ROUTE_KEY, route)
    return route


def provider_client(provider_id: str) -> ApimartClient | None:
    p = next((x for x in _raw() if x["id"] == provider_id), None)
    if p is None:
        return None
    return ApimartClient(p["base_url"], secretbox.decrypt(p["key_enc"]), p["model"], p.get("params"))
