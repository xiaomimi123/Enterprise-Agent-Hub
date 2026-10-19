"""GPU 调度：任务排队、派发给空闲的 ComfyUI 节点、取回结果。

- MCP 工具调用 submit_task() 把任务放进队列（数据库 gpu_tasks），再用 wait_task() 等结果
- 调度服务（python -m app.gpu）循环执行：刷新节点状态 → 给空闲节点派任务 → 收取已完成任务的图片
- 每个节点同一时间只跑一个任务，其余排队；结果图片存到 HUB_OUTPUTS_DIR，通过带签名的链接下载
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from datetime import datetime

import httpx
from pathlib import Path
from urllib.parse import urlencode

from . import db
from . import imageapi
from .comfyui import ComfyUI, load_workflow
from .config import settings

log = logging.getLogger("hub.gpu")
LINK_TTL = 7 * 86400  # 下载链接有效期
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".gif"}


def parse_nodes(spec: str) -> list[dict]:
    nodes = []
    for item in filter(None, (x.strip() for x in spec.split(","))):
        parts = [p.strip() for p in item.split("|")]
        if len(parts) < 3:
            continue
        nodes.append({"id": parts[0], "name": parts[1], "url": parts[2], "gpu": parts[3] if len(parts) > 3 else ""})
    return nodes


# ---- 下载链接 ----

def _sign(path: str, exp: int) -> str:
    return hmac.new(settings.file_secret.encode(), f"{path}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def file_url(task_id: str, name: str) -> str:
    path = f"{task_id}/{name}"
    exp = int(time.time()) + LINK_TTL
    return f"{settings.public_url}/api/files/{path}?" + urlencode({"exp": exp, "sig": _sign(path, exp)})


def verify_file(task_id: str, name: str, exp: int, sig: str) -> Path | None:
    path = f"{task_id}/{name}"
    if not settings.file_secret or exp < time.time() or not hmac.compare_digest(_sign(path, exp), sig):
        return None
    f = (Path(settings.outputs_dir) / task_id / name).resolve()
    if Path(settings.outputs_dir).resolve() not in f.parents or not f.is_file():
        return None
    return f


# ---- 提交与等待（MCP 工具调用）----

def submit_task(*, trace_id: str, org: str, user_name: str, display_name: str, dept: str, channel: str,
                workflow: str, params: dict) -> dict:
    task = {"id": f"gpu-{uuid.uuid4().hex[:12]}", "trace_id": trace_id, "org": org, "user_name": user_name,
            "display_name": display_name, "dept": dept, "channel": channel, "workflow": workflow, "params": params}
    db.create_gpu_task(task)
    return {**task, "ahead": db.queue_position(task["id"])}


def wait_task(task_id: str, timeout: float) -> dict:
    deadline = time.time() + timeout
    while True:
        t = db.gpu_task(task_id)
        if t["status"] in ("done", "failed") or time.time() >= deadline:
            return t
        time.sleep(1)


def describe(t: dict) -> dict:
    """给 agent 看的任务结果。"""
    out = {"task_id": t["id"], "status": {"queued": "排队中", "running": "生成中", "done": "已完成", "failed": "失败"}[t["status"]]}
    if t["status"] == "queued":
        out["ahead"] = db.queue_position(t["id"])
    if t["node_id"]:
        out["node"] = t["node_id"]
    if t["status"] == "done":
        is_video = lambda n: Path(n).suffix.lower() in VIDEO_SUFFIXES  # noqa: E731
        out["images"] = [file_url(t["id"], n) for n in t["images"] if not is_video(n)]
        if any(is_video(n) for n in t["images"]):
            out["videos"] = [file_url(t["id"], n) for n in t["images"] if is_video(n)]
        if t["started_at"] and t["finished_at"]:
            out["seconds"] = round((t["finished_at"] - t["started_at"]).total_seconds(), 1)
    if t["status"] == "failed":
        out["error"] = t["error"]
    return out


STATUS_TEXT = {"queued": "排队中", "running": "生成中", "done": "已完成", "failed": "失败"}


def list_tasks(limit: int = 100) -> dict:
    """控制台「生成任务」页：最近的任务（新的在前）和队列概况。"""
    rows = db.recent_gpu_tasks(limit)
    ahead = {r["id"]: i for i, r in enumerate(sorted((r for r in rows if r["status"] == "queued"),
                                                     key=lambda r: r["created_at"]))}
    today = datetime.now().astimezone().date()
    tasks = []
    for t in rows:
        p = t["params"] or {}
        files = [{"type": "video" if Path(n).suffix.lower() in VIDEO_SUFFIXES else "image", "url": file_url(t["id"], n)}
                 for n in t["images"]]
        started, finished = t["started_at"], t["finished_at"]
        tasks.append({
            "id": t["id"], "trace_id": t["trace_id"], "member": t["display_name"] or t["user_name"],
            "member_id": t["user_name"], "dept": t["dept"], "channel": t["channel"],
            "kind": "video" if t["workflow"].startswith("video-") else "image", "workflow": t["workflow"],
            "via": "第三方 API" if t["workflow"] == "api-image" else "本机 GPU",
            "title": p.get("title", ""), "prompt": p.get("prompt", ""),
            "size": f"{p['width']}×{p['height']}" if p.get("width") else "", "count": p.get("count", 1),
            "status": STATUS_TEXT[t["status"]], "node_id": t["node_id"], "ahead": ahead.get(t["id"]),
            "created_at": t["created_at"].astimezone().replace(microsecond=0).isoformat(),
            "wait_seconds": round((started - t["created_at"]).total_seconds()) if started else None,
            "run_seconds": round((finished - started).total_seconds()) if started and finished else None,
            "error": t["error"], "files": files,
        })
    def n(status: str) -> int:
        return sum(1 for t in rows if t["status"] == status)
    return {
        "summary": {"queued": n("queued"), "running": n("running"), "failed": n("failed"),
                    "done_today": sum(1 for t in rows if t["status"] == "done" and t["finished_at"]
                                      and t["finished_at"].astimezone().date() == today)},
        "tasks": tasks,
    }


# ---- 调度服务 ----

def _audit(t: dict, detail: str, result: str) -> None:
    db.add_audit(trace_id=t["trace_id"], org=t["org"], user_name=t["user_name"], display_name=t["display_name"],
                 dept=t["dept"], channel=t["channel"], kind="生成", tool=(t["params"] or {}).get("tool", "image.cover"),
                 detail=detail, result=result)


# ---- 容错：节点掉线 / 派发中断 / 超时 → 重新排队，最多重试 1 次 ----

TIMEOUT_SECONDS = {"image-gen": 600, "video-h3": 1800, "video-h3-i2v": 1800}
DEFAULT_TIMEOUT = 1200
OFFLINE_GRACE = 30        # 刚派发时节点状态可能还没刷新，给一点余量
DISPATCH_GRACE = 120      # 领取了任务却一直没拿到 ComfyUI 任务号（派发中途调度服务重启等）
MAX_ATTEMPTS = 2          # 首次 + 重试 1 次


def _recover(nodes: dict[str, dict], online: set[str], now: datetime | None = None) -> None:
    now = now or datetime.now().astimezone()
    for t in db.running_tasks():
        if not t["started_at"]:
            continue
        elapsed = (now - t["started_at"]).total_seconds()
        node = nodes.get(t["node_id"]) or {"name": t["node_id"] or "未知节点"}
        if not t["prompt_id"] and elapsed > DISPATCH_GRACE:
            reason = "派发中断"
        elif t["node_id"] not in online and elapsed > OFFLINE_GRACE:
            reason = f"{node['name']} 掉线"
        elif elapsed > TIMEOUT_SECONDS.get(t["workflow"], DEFAULT_TIMEOUT):
            reason = f"{node['name']} 运行超时（{elapsed / 60:.0f} 分钟）"
            if t["prompt_id"] and node.get("url"):
                try:
                    ComfyUI(node["url"]).cancel(t["prompt_id"])
                except Exception:  # noqa: BLE001 取消失败不影响改派
                    log.warning("取消 ComfyUI 任务 %s 失败", t["prompt_id"])
        else:
            continue
        if (t.get("attempts") or 0) + 1 < MAX_ATTEMPTS:
            db.requeue_gpu_task(t["id"])
            _audit(t, f"{reason}，任务已重新排队（第 {(t.get('attempts') or 0) + 2} 次）", "通过")
            log.warning("任务 %s：%s，重新排队", t["id"], reason)
        else:
            db.update_gpu_task(t["id"], status="failed", error=f"{reason}，重试后仍未完成")
            _audit(t, f"{reason}，重试后仍未完成，任务失败", "拒绝")
            log.warning("任务 %s：%s，已失败", t["id"], reason)


def _refresh_nodes(nodes: list[dict]) -> set[str]:
    online = set()
    for n in nodes:
        try:
            dev = (ComfyUI(n["url"]).stats().get("devices") or [{}])[0]
            db.update_node_status(n["id"], True, int(dev.get("vram_total") or 0), int(dev.get("vram_free") or 0))
            online.add(n["id"])
        except Exception:  # noqa: BLE001 节点离线或网络异常
            db.update_node_status(n["id"], False)
    return online


def _dispatch(nodes: list[dict], online: set[str]) -> None:
    for n in nodes:
        if n["id"] not in online:
            continue
        t = db.claim_task_for(n["id"])
        if not t:
            continue
        try:
            client = ComfyUI(n["url"])
            params = dict(t["params"])
            if params.get("_input"):  # 图生视频：先把参考图传到这个节点的 ComfyUI
                src = Path(settings.outputs_dir) / params["_input"]
                params["image"] = client.upload_image(f"hub-{t['id']}{src.suffix}", src.read_bytes())
            wf, outputs = load_workflow(t["workflow"], **params)
            prompt_id = client.submit(wf)
            db.update_gpu_task(t["id"], prompt_id=prompt_id, params={**t["params"], "_outputs": outputs})
            log.info("任务 %s 派发到 %s", t["id"], n["id"])
        except Exception as e:  # noqa: BLE001
            db.update_gpu_task(t["id"], status="failed", error=str(e)[:500])
            _audit(t, f"派发到 {n['name']} 失败：{e}", "拒绝")


def _collect(nodes: dict[str, dict]) -> None:
    for t in db.running_tasks():
        node = nodes.get(t["node_id"])
        if not node or not t["prompt_id"]:
            continue
        try:
            client = ComfyUI(node["url"])
            status, images = client.result(t["prompt_id"], t["params"].get("_outputs", []))
            if status == "running":
                continue
            if status == "error" or not images:
                raise RuntimeError("ComfyUI 执行失败或没有输出")
            folder = Path(settings.outputs_dir) / t["id"]
            folder.mkdir(parents=True, exist_ok=True)
            names = []
            for i, img in enumerate(images, 1):
                name = f"{i}{Path(img['filename']).suffix.lower() or '.png'}"
                (folder / name).write_bytes(client.download(img))
                names.append(name)
            db.update_gpu_task(t["id"], status="done", images=names)
            took = time.time() - t["started_at"].timestamp()
            unit = "条视频" if names[0].endswith(tuple(VIDEO_SUFFIXES)) else "张"
            _audit(t, f"{node['name']} 生成 {len(names)} {unit}「{t['params'].get('title', '')}」，耗时 {took:.0f} 秒", "通过")
            log.info("任务 %s 完成，%d 张", t["id"], len(names))
        except httpx.HTTPError as e:  # 网络抖动或节点暂时连不上：下一轮再查，掉线由 _recover 处理
            log.warning("任务 %s 暂时取不到结果：%s", t["id"], e)
        except Exception as e:  # noqa: BLE001
            db.update_gpu_task(t["id"], status="failed", error=str(e)[:500])
            _audit(t, f"{node['name']} 生成失败：{e}", "拒绝")


# ---- 第三方 API 出图（workflow = api-image）----

API_TIMEOUT_SECONDS = 600


def _api_fail(t: dict, reason: str) -> None:
    db.update_gpu_task(t["id"], status="failed", error=reason[:500])
    _audit(t, f"第三方 API 出图失败：{reason}", "拒绝")
    log.warning("任务 %s 第三方 API 出图失败：%s", t["id"], reason)


def _api_submit(t: dict, client_factory) -> None:
    provider = imageapi.default_provider()
    if provider is None:
        return _api_fail(t, "没有可用的出图 API，请在「模型」页添加并启用")
    p = t["params"]
    try:
        external = client_factory(provider["id"]).submit(p.get("prompt", ""), int(p.get("width", 1024)),
                                                          int(p.get("height", 1024)), int(p.get("count", 1)))
    except imageapi.ImageApiError as e:
        return _api_fail(t, str(e))
    # 先把第三方任务号落库：调度服务重启后凭它恢复轮询，不会重复提交（重复提交 = 重复付费）
    db.update_gpu_task(t["id"], prompt_id=external, params={**p, "_provider": provider["id"]})
    log.info("任务 %s 已提交第三方 API（%s）", t["id"], external)


def _api_collect(t: dict, client_factory, now: datetime) -> None:
    elapsed = (now - t["started_at"]).total_seconds() if t["started_at"] else 0
    if not t["prompt_id"]:
        if elapsed > DISPATCH_GRACE:  # 领取了任务却一直没拿到第三方任务号（提交中途调度服务重启等）
            if (t.get("attempts") or 0) + 1 < MAX_ATTEMPTS:
                db.requeue_gpu_task(t["id"])
                _audit(t, "派发中断，任务已重新排队", "通过")
            else:
                _api_fail(t, "派发中断，重试后仍未完成")
        return
    if elapsed > API_TIMEOUT_SECONDS:
        return _api_fail(t, f"第三方 API 超时（{elapsed / 60:.0f} 分钟）")
    try:
        client = client_factory(t["params"].get("_provider", ""))
        state, urls = client.poll(t["prompt_id"])
    except imageapi.ImageApiError as e:  # 网络抖动或第三方暂时出错：下一轮再查，超时由上面处理
        log.warning("任务 %s 暂时查不到结果：%s", t["id"], e)
        return
    if state == "running":
        return
    if state == "failed":
        return _api_fail(t, "第三方返回失败")
    if not urls:
        return _api_fail(t, "第三方完成了但没有返回图片")
    try:
        folder = Path(settings.outputs_dir) / t["id"]
        folder.mkdir(parents=True, exist_ok=True)
        names = []
        for i, url in enumerate(urls, 1):
            name = f"{i}{Path(url.split('?')[0]).suffix.lower() or '.png'}"
            (folder / name).write_bytes(client.download(url))
            names.append(name)
    except (imageapi.ImageApiError, OSError) as e:
        return _api_fail(t, f"下载图片失败：{e}")
    db.update_gpu_task(t["id"], status="done", images=names)
    _audit(t, f"第三方 API 生成 {len(names)} 张「{t['params'].get('title', '')}」，耗时 {elapsed:.0f} 秒", "通过")
    log.info("任务 %s 完成（第三方 API），%d 张", t["id"], len(names))


def run_api_step(client_factory=imageapi.provider_client, now: datetime | None = None) -> None:
    """调度服务每轮调用：先收取在跑任务的结果，再领取新任务提交给第三方（同时进行数有上限）。"""
    now = now or datetime.now().astimezone()
    for t in db.running_api_tasks():
        _api_collect(t, client_factory, now)
    for t in db.claim_api_tasks(settings.image_api_max_concurrency):
        _api_submit(t, client_factory)


def run_worker(interval: float = 1.0) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 不逐条打印轮询请求
    nodes = parse_nodes(settings.gpu_nodes)
    db.init_schema()
    db.sync_gpu_nodes(nodes)
    log.info("GPU 调度服务启动，节点：%s", ", ".join(f"{n['id']}({n['url']})" for n in nodes) or "无")
    online: set[str] = set()
    last_refresh = 0.0
    by_id = {n["id"]: n for n in nodes}
    while True:
        try:
            if time.time() - last_refresh > 10:
                online = _refresh_nodes(nodes)
                last_refresh = time.time()
            _collect(by_id)
            _recover(by_id, online)
            _dispatch(nodes, online)
            run_api_step()
        except Exception:  # noqa: BLE001 数据库短暂不可用等情况，下一轮重试
            log.exception("调度循环出错")
        time.sleep(interval)


if __name__ == "__main__":
    run_worker()
