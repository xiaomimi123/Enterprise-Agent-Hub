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

VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv", ".mov")


def is_video(name: str) -> bool:
    return name.lower().endswith(VIDEO_SUFFIXES)


# 视频帧数必须是 17k+5 网格（MiniMax H3 的硬约束），分辨率必须是 32 的倍数
FRAME_GRID = [5, 22, 39, 56, 73, 90, 107, 124, 141, 158, 175, 192, 209, 226]


def frames_for_seconds(seconds: float, fps: float = 24.0) -> int:
    """把「想要几秒」换算成网格帧数：取不小于要求时长的最小值（宁可略长，不要给短了）。

    例：24fps 下要 4 秒 = 96 帧 → 107 帧（约 4.5 秒），与模型交接文档的建议值一致。
    """
    want = max(1.0, seconds) * fps
    return next((f for f in FRAME_GRID if f >= want), FRAME_GRID[-1])


def build_timeline(prompt: str, image_file: str | None, frames: int, width: int, height: int,
                   fps: float = 24.0) -> str:
    """MiniMaxH3Director 的 timeline_data（JSON 字符串）。

    给了 image_file 就是图生视频（R2V，refs 里必须带参考图）；不给就是文生视频（T2V，refs 留空）。
    """
    r2v = "r2v — 参考主体生视频(Reference to Video)" if image_file else "t2v — 文生视频(Text to Video)"
    refs = [{"index": 0, "imageFile": image_file}] if image_file else []
    return json.dumps({
        "version": 4, "editMode": "global", "totalFrames": frames, "frameRate": fps,
        "width": width, "height": height, "refMaxSize": min(width, height),
        "output": {"mode": "fixed", "longEdge": min(width, height), "width": width, "height": height,
                   "maxExportFrames": 0, "exportMode": "all", "audioMode": "generate", "refImageSize": "match"},
        "videoClips": [],
        "video": {"fileName": "", "videoFile": "", "subfolder": "", "type": "input", "frames": [], "frameMap": []},
        "global": {"taskType": r2v, "prompt": prompt, "refs": refs,
                   "referenceVideo": {}, "continuousReference": False},
        "segments": [{"id": "s0", "start": 0, "length": frames, "frameCount": frames, "prompt": prompt,
                      "taskType": r2v, "refs": refs, "referenceVideo": {}}],
    }, ensure_ascii=False)


DEFAULT_WAIT = 90  # 生图默认等 90 秒；工作流可在 _meta.wait_seconds 里覆盖（视频是分钟级）


def workflow_meta(name: str) -> dict:
    """工作流模板的 _meta（名称、输出节点、等待时长、类型）。模板不存在时返回空（调用方有默认值）。"""
    path = Path(settings.workflows_dir) / f"{name}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text()).get("_meta", {})


def load_workflow(name: str, **values: object) -> tuple[dict, list[str]]:
    """读取工作流模板并替换占位符，返回（工作流, 输出节点 id 列表）。"""
    raw = (Path(settings.workflows_dir) / f"{name}.json").read_text()
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
        """返回（状态, 结果文件列表）。状态：running / success / error。

        图片在 outputs[].images，视频在 outputs[].videos（ComfyUI 的 SaveVideo 节点）——
        两种都归一化成带 filename/subfolder/type 的记录，取回时用同一个 /view 接口。
        """
        h = self.http.get(f"/history/{prompt_id}").json().get(prompt_id)
        if not h:
            return "running", []
        status = (h.get("status") or {}).get("status_str", "success")
        if status == "error":
            return "error", []
        files = []
        for node_id, out in (h.get("outputs") or {}).items():
            if outputs and node_id not in outputs:
                continue
            for key in ("images", "videos", "gifs"):
                files += out.get(key, [])
        return "success", files

    def download(self, item: dict) -> bytes:
        r = self.http.get("/view", params={"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                           "type": item.get("type", "output")})
        r.raise_for_status()
        return r.content

    def upload_image(self, name: str, data: bytes, subfolder: str = "", overwrite: bool = True) -> str:
        """上传参考图（图生视频用），返回 ComfyUI 里的文件名。"""
        files = {"image": (name, data, "application/octet-stream")}
        r = self.http.post("/upload/image", files=files,
                           data={"overwrite": "true" if overwrite else "false", "subfolder": subfolder})
        body = r.json()
        if r.status_code != 200 or not body.get("name"):
            raise RuntimeError(f"ComfyUI 上传参考图失败：{body.get('error') or r.text[:200]}")
        return f"{body.get('subfolder') + '/' if body.get('subfolder') else ''}{body['name']}"

    def stats(self) -> dict:
        return self.http.get("/system_stats", timeout=5).json()
