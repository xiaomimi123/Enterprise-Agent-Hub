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
from pathlib import Path
from urllib.parse import urlencode

from . import db
from .comfyui import ComfyUI, load_workflow
from .config import settings

log = logging.getLogger("hub.gpu")
LINK_TTL = 7 * 86400  # 下载链接有效期


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
        out["images"] = [file_url(t["id"], name) for name in t["images"]]
        if t["started_at"] and t["finished_at"]:
            out["seconds"] = round((t["finished_at"] - t["started_at"]).total_seconds(), 1)
    if t["status"] == "failed":
        out["error"] = t["error"]
    return out


# ---- 调度服务 ----

def _audit(t: dict, detail: str, result: str) -> None:
    db.add_audit(trace_id=t["trace_id"], org=t["org"], user_name=t["user_name"], display_name=t["display_name"],
                 dept=t["dept"], channel=t["channel"], kind="工具", tool="image.cover", detail=detail, result=result)


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
            wf, outputs = load_workflow(t["workflow"], **t["params"])
            prompt_id = ComfyUI(n["url"]).submit(wf)
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
                raise RuntimeError("ComfyUI 执行失败或没有输出图片")
            folder = Path(settings.outputs_dir) / t["id"]
            folder.mkdir(parents=True, exist_ok=True)
            names = []
            for i, img in enumerate(images, 1):
                name = f"{i}.png"
                (folder / name).write_bytes(client.download(img))
                names.append(name)
            db.update_gpu_task(t["id"], status="done", images=names)
            took = time.time() - t["started_at"].timestamp()
            _audit(t, f"{node['name']} 生成 {len(names)} 张「{t['params'].get('title', '')}」，耗时 {took:.0f} 秒", "通过")
            log.info("任务 %s 完成，%d 张", t["id"], len(names))
        except Exception as e:  # noqa: BLE001
            db.update_gpu_task(t["id"], status="failed", error=str(e)[:500])
            _audit(t, f"{node['name']} 生成失败：{e}", "拒绝")


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
            _dispatch(nodes, online)
        except Exception:  # noqa: BLE001 数据库短暂不可用等情况，下一轮重试
            log.exception("调度循环出错")
        time.sleep(interval)


if __name__ == "__main__":
    run_worker()
