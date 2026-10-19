"""H3 生成网关（本机的 minimax h3 目录下的 genapi 服务）：配置（存数据库、密钥加密）与异步客户端。

网关把本机 ComfyUI 的 MiniMax H3 / Z-Image 能力包成 REST：POST /api/v1/generate/{mode} → job_id →
GET /api/v1/jobs/{id} 轮询（queued / running / done / error）→ GET /api/v1/jobs/{id}/video 下载（图片任务下载的也是这个地址）。
鉴权是请求头 X-API-Key，单卡串行、没有取消接口，所以中枢自己排队，一次只往网关放少量任务。
- 通道开关：`image.route` 增加取值 `h3`；视频新增 `video.route`（`gpu` 默认 / `h3`）
- 网关只认一个共用 Key，具体是哪位员工提交的记录在中枢审计里
- 密钥只加密落库，接口只回后四位；所有错误信息过滤掉密钥
"""

from __future__ import annotations

import base64
import random
import time

import httpx

from . import secretbox, settings_store


class H3Error(Exception):
    """配置不合法或网关出错，消息可以直接给管理员看（不含密钥）。"""


GATEWAY_KEY, VIDEO_ROUTE_KEY = "h3.gateway", "video.route"
POLL_INTERVAL = 3.0


def _scrub(msg: str, key: str) -> str:
    return msg.replace(key, "••••") if key else msg


def normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")) or len(url) < 9:
        raise H3Error("地址必须以 http:// 或 https:// 开头")
    return url[:-len("/api/v1")].rstrip("/") if url.endswith("/api/v1") else url


class H3Client:
    def __init__(self, base_url: str, key: str, verify_tls: bool = True, client: httpx.Client | None = None):
        self.base_url, self.key = base_url.rstrip("/"), key
        self.http = client or httpx.Client(timeout=60, follow_redirects=True, verify=verify_tls)

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = self.http.request(method, f"{self.base_url}/api/v1{path}", headers={"X-API-Key": self.key}, **kw)
        except httpx.HTTPError as e:
            raise H3Error(_scrub(f"连接 H3 网关失败：{e}", self.key)) from None
        if r.status_code >= 400:
            raise H3Error(_scrub(f"H3 网关返回 HTTP {r.status_code}：{r.text[:200]}", self.key))
        return r

    def health(self) -> dict:
        return self._request("GET", "/health").json()

    def submit(self, mode: str, prompt: str, *, width: int | None = None, height: int | None = None,
               frames: int | None = None, fps: int | None = None, image: bytes | None = None,
               seed: int | None = None) -> str:
        """mode：t2i / t2v / i2v。返回网关的 job_id。"""
        body: dict = {"prompt": prompt, "seed": random.randint(1, 2**31) if seed is None else seed}
        for k, v in (("width", width), ("height", height), ("total_frames", frames), ("frame_rate", fps)):
            if v:
                body[k] = int(v)
        if image is not None:
            body["reference_images"] = [{"filename": "first.png", "data_base64": base64.b64encode(image).decode()}]
        r = self._request("POST", f"/generate/{mode}", json=body, timeout=120)
        job = r.json().get("job_id")
        if not job:
            raise H3Error("H3 网关没有返回任务号")
        return str(job)

    def poll(self, job_id: str) -> tuple[str, str]:
        """返回 (running | done | failed, 失败原因)。"""
        d = self._request("GET", f"/jobs/{job_id}").json()
        status = str(d.get("status") or "").lower()
        if status == "error":
            return "failed", str(d.get("error") or "H3 网关返回失败")
        return ("done" if status == "done" else "running"), ""

    def download(self, job_id: str) -> bytes:
        return self._request("GET", f"/jobs/{job_id}/video", timeout=300).content

    def test(self) -> dict:
        """真实出一张 512×512 的图，返回 {ok, seconds, error, preview}；不计入员工任务。"""
        start = time.time()
        try:
            job = self.submit("t2i", "a small red circle on white background", width=512, height=512)
            while time.time() - start < 180:
                state, reason = self.poll(job)
                if state == "failed":
                    return {"ok": False, "seconds": round(time.time() - start, 1), "error": reason}
                if state == "done":
                    data = self.download(job)
                    return {"ok": True, "seconds": round(time.time() - start, 1), "error": "",
                            "preview": "data:image/png;base64," + base64.b64encode(data).decode()}
                time.sleep(POLL_INTERVAL)
            return {"ok": False, "seconds": 180.0, "error": "180 秒内没有出图"}
        except H3Error as e:
            return {"ok": False, "seconds": round(time.time() - start, 1), "error": str(e)}


# ---- 配置 ----

def _raw() -> dict | None:
    return settings_store.get(GATEWAY_KEY, None) or None


def get_gateway() -> dict | None:
    g = _raw()
    if g is None:
        return None
    return {"base_url": g["base_url"], "enabled": bool(g.get("enabled", True)), "verify_tls": bool(g.get("verify_tls", True)),
            "key_hint": g.get("key_hint", "")}


def save_gateway(base_url: str, key: str | None, enabled: bool | None = None, verify_tls: bool | None = None) -> dict:
    """新增或修改（只有一个网关）；key 留空表示不改，首次保存必须填。"""
    old = _raw()
    url = normalize_url(base_url)
    if (key or "").strip():
        enc, hint = secretbox.encrypt(key.strip()), secretbox.mask_secret(key.strip())
    elif old:
        enc, hint = old["key_enc"], old.get("key_hint", "")
    else:
        raise H3Error("请填写密钥")
    g = {"base_url": url, "key_enc": enc, "key_hint": hint,
         "enabled": (old or {}).get("enabled", True) if enabled is None else enabled,
         "verify_tls": (old or {}).get("verify_tls", True) if verify_tls is None else verify_tls}
    settings_store.put(GATEWAY_KEY, g)
    _fallback_routes(g)
    return get_gateway()


def remove_gateway() -> bool:
    if _raw() is None:
        return False
    settings_store.put(GATEWAY_KEY, None)
    _fallback_routes(None)
    return True


def client() -> H3Client | None:
    """已启用的网关客户端（含解密后的密钥，只在内部调用时用）；没配置或已停用返回 None。"""
    g = _raw()
    if g is None or not g.get("enabled", True):
        return None
    return H3Client(g["base_url"], secretbox.decrypt(g["key_enc"]), g.get("verify_tls", True))


def usable() -> bool:
    g = _raw()
    return bool(g and g.get("enabled", True))


def get_video_route() -> str:
    try:
        return settings_store.get(VIDEO_ROUTE_KEY, "gpu") or "gpu"
    except RuntimeError:  # 没有数据库（演示模式）：一律走本机 GPU
        return "gpu"


def set_video_route(route: str) -> str:
    if route not in ("gpu", "h3"):
        raise H3Error("视频通道只能是 gpu 或 h3")
    if route == "h3" and not usable():
        raise H3Error("没有可用的 H3 网关，请先添加并启用")
    settings_store.put(VIDEO_ROUTE_KEY, route)
    return route


def _fallback_routes(g: dict | None) -> None:
    """网关被删除或停用后，指向它的通道自动退回本机 GPU，不让新任务提交到一个不可用的通道。"""
    if g is not None and g.get("enabled", True):
        return
    if get_video_route() == "h3":
        settings_store.put(VIDEO_ROUTE_KEY, "gpu")
    if settings_store.get("image.route", "gpu") == "h3":
        settings_store.put("image.route", "gpu")
