"""ComfyUI 客户端与工作流模板。

GPU 能力节点就是一台跑着 ComfyUI 的机器。中枢通过 ComfyUI 的标准 HTTP 接口派发任务：
POST /prompt 提交工作流 → GET /history/{prompt_id} 查结果 → GET /view 取图片；GET /system_stats 查显卡状态。

工作流模板放在 gpu-node/workflows/<名称>.json（ComfyUI 的 API 格式），其中 {{占位符}} 在派发时替换。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import httpx

from .config import settings

NEGATIVE = "lowres, blurry, watermark, text artifacts, extra fingers, deformed"


def load_workflow(name: str, **values: object) -> tuple[dict, list[str]]:
    """读取工作流模板并替换占位符，返回（工作流, 输出节点 id 列表）。"""
    raw = (Path(settings.workflows_dir) / f"{name}.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    meta = data.pop("_meta", {})
    values = {"negative": NEGATIVE, "seed": random.randint(1, 2**31 - 1), "checkpoint": settings.comfy_checkpoint, **values}

    def fill(node: object) -> object:
        if isinstance(node, dict):
            return {k: fill(v) for k, v in node.items()}
        if isinstance(node, list):
            return [fill(v) for v in node]
        if isinstance(node, str) and node.startswith("{{") and node.endswith("}}"):
            return values[node[2:-2]]  # 整个值就是占位符：保留原类型（如 seed 是整数）
        if isinstance(node, str):
            for k, v in values.items():
                node = node.replace("{{" + k + "}}", str(v))
        return node

    return fill(data), meta.get("outputs", [])


class ComfyUI:
    def __init__(self, url: str, timeout: float = 15):
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout)

    def submit(self, workflow: dict) -> str:
        r = self.http.post("/prompt", json={"prompt": workflow, "client_id": "hub"})
        body = r.json()
        if r.status_code != 200 or "prompt_id" not in body:
            raise RuntimeError(f"ComfyUI 拒绝了任务：{body.get('error') or body.get('node_errors') or r.text[:200]}")
        return body["prompt_id"]

    def result(self, prompt_id: str, outputs: list[str]) -> tuple[str, list[dict]]:
        """返回（状态, 图片列表）。状态：running / success / error。"""
        h = self.http.get(f"/history/{prompt_id}").json().get(prompt_id)
        if not h:
            return "running", []
        status = (h.get("status") or {}).get("status_str", "success")
        if status == "error":
            return "error", []
        images = []
        for node_id, out in (h.get("outputs") or {}).items():
            if outputs and node_id not in outputs:
                continue
            images += out.get("images", [])
        return "success", images

    def download(self, image: dict) -> bytes:
        r = self.http.get("/view", params={"filename": image["filename"], "subfolder": image.get("subfolder", ""),
                                           "type": image.get("type", "output")})
        r.raise_for_status()
        return r.content

    def upload_image(self, name: str, data: bytes) -> str:
        """上传参考图到 ComfyUI 的 input 目录，返回工作流 LoadImage 里要填的文件名。"""
        r = self.http.post("/upload/image", files={"image": (name, data)}, data={"overwrite": "true"}, timeout=60)
        r.raise_for_status()
        body = r.json()
        return f"{body['subfolder']}/{body['name']}" if body.get("subfolder") else body["name"]

    def cancel(self, prompt_id: str) -> None:
        """取消一个任务：还在排队就从队列删掉，正在跑就中断。"""
        self.http.post("/queue", json={"delete": [prompt_id]})
        running = (self.http.get("/queue").json().get("queue_running") or [])
        if any(len(item) > 1 and item[1] == prompt_id for item in running):
            self.http.post("/interrupt", json={"prompt_id": prompt_id})

    def stats(self) -> dict:
        return self.http.get("/system_stats", timeout=5).json()
