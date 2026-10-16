"""GPU 调度：任务排队、派发给空闲的 ComfyUI 节点、取回结果。
（调度服务顺带每 10 分钟按岗位包重新下发员工的模型限制与额度，见 entitlements.resync_all）

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

from . import comfyui, db
from .comfyui import ComfyUI, load_workflow, workflow_meta
from .config import settings

log = logging.getLogger("hub.gpu")
LINK_TTL = 7 * 86400  # 下载链接有效期

# 调度用的工作流注册表：MCP 工具按名字派发，等待时长与输出类型取自模板的 _meta。
# 模板放在 gpu-node/workflows/，设计师在 ComfyUI 里调好后导出（API 格式）替换即可，不用改代码。
WORKFLOWS = {
    "xhs-cover": {"label": "小红书封面", "kind": "image", "tool": "image.cover"},
    "zimage-cover": {"label": "封面图（Z-Image）", "kind": "image", "tool": "image.cover"},
    "minimax-video": {"label": "短视频（图生视频）", "kind": "video", "tool": "video.clip"},
    "minimax-video-t2v": {"label": "短视频（文生视频）", "kind": "video", "tool": "video.clip"},
}
DEFAULT_WAIT = 90  # 生图默认等 90 秒；工作流可在 _meta.wait_seconds 里覆盖（视频是分钟级）


def workflow_spec(name: str) -> dict:
    """工作流的调度参数：注册表为准，等待时长取模板 _meta（缺失则按类型给默认值）。"""
    spec = {"kind": "image", "tool": "image.cover", "label": name, **WORKFLOWS.get(name, {})}
    meta = workflow_meta(name)
    spec["kind"] = meta.get("kind", spec["kind"])
    spec["wait_seconds"] = int(meta.get("wait_seconds") or (60 * 30 if spec["kind"] == "video" else DEFAULT_WAIT))
    spec["label"] = meta.get("name") or spec["label"]
    return spec


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
    return {**task, "ahead": db.queue_position(task["id"]), "spec": workflow_spec(workflow)}


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
        # 按存下来的文件名判断是图还是视频（下载链接带 ?exp=&sig= 后缀，不能拿链接判断）
        videos = [file_url(t["id"], n) for n in t["images"] if comfyui.is_video(n)]
        images = [file_url(t["id"], n) for n in t["images"] if not comfyui.is_video(n)]
        if videos:
            out["videos"] = videos
        if images:
            out["images"] = images
        if t["started_at"] and t["finished_at"]:
            out["seconds"] = round((t["finished_at"] - t["started_at"]).total_seconds(), 1)
    if t["status"] == "failed":
        out["error"] = t["error"]
    return out


# ---- 调度服务 ----

def online_node() -> dict | None:
    """挑一个在线的 GPU 节点（图生视频要先把参考图传到节点上，派发前得知道往哪传）。"""
    return next((n for n in db.gpu_nodes() if n["online"]), None)


def _audit(t: dict, detail: str, result: str) -> None:
    db.add_audit(trace_id=t["trace_id"], org=t["org"], user_name=t["user_name"], display_name=t["display_name"],
                 dept=t["dept"], channel=t["channel"], kind="工具",
                 tool=workflow_spec(t["workflow"])["tool"], detail=detail, result=result)


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
                raise RuntimeError("ComfyUI 执行失败或没有输出文件")
            folder = Path(settings.outputs_dir) / t["id"]
            folder.mkdir(parents=True, exist_ok=True)
            names = []
            for i, item in enumerate(images, 1):
                # 保留节点给出的扩展名：视频是 .mp4，一律写成 .png 会让下载时的媒体类型出错
                suffix = Path(item.get("filename", "")).suffix or ".png"
                name = f"{i}{suffix}"
                (folder / name).write_bytes(client.download(item))
                names.append(name)
            db.update_gpu_task(t["id"], status="done", images=names)
            took = time.time() - t["started_at"].timestamp()
            unit = "条视频" if any(comfyui.is_video(n) for n in names) else "张图"
            _audit(t, f"{node['name']} 生成 {len(names)} {unit}「{t['params'].get('title', '')}」，耗时 {took:.0f} 秒", "通过")
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
    last_resync = 0.0
    by_id = {n["id"]: n for n in nodes}
    while True:
        try:
            if time.time() - last_refresh > 10:
                online = _refresh_nodes(nodes)
                last_refresh = time.time()
            _collect(by_id)
            _dispatch(nodes, online)
            if time.time() - last_resync > 600 and settings.casdoor_org:
                from . import entitlements
                n = entitlements.resync_all(settings.casdoor_org)
                last_resync = time.time()
                log.info("已按岗位包重新下发 %d 名员工的模型限制与额度", n)
        except Exception:  # noqa: BLE001 数据库短暂不可用等情况，下一轮重试
            log.exception("调度循环出错")
        time.sleep(interval)


if __name__ == "__main__":
    run_worker()
