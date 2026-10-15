"""开发用的模拟 ComfyUI 节点，只在演示/开发环境部署（没有 N 卡时用来跑通 GPU 调度链路）。

实现与真 ComfyUI 相同的接口：POST /prompt、GET /history/{id}、GET /view、GET /queue、GET /system_stats。
收到工作流后排队，一次只处理一个（和真显卡一样），每个任务约 4 秒，按工作流里的提示词画 3 张占位封面图。

运行：uvicorn app.mock_comfyui:app --port 8188
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import textwrap
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from PIL import Image, ImageDraw, ImageFont

RENDER_SECONDS = float(os.getenv("MOCK_COMFYUI_SECONDS", "4"))
PALETTES = [((247, 236, 222), (196, 120, 90)), ((232, 240, 236), (63, 120, 98)), ((238, 236, 250), (91, 91, 214))]
FONTS = ["/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "/System/Library/Fonts/PingFang.ttc",
         "/System/Library/Fonts/STHeiti Medium.ttc"]

app = FastAPI(title="模拟 ComfyUI（开发用）")
queue: asyncio.Queue = asyncio.Queue()
history: dict[str, dict] = {}
files: dict[str, bytes] = {}
state = {"running": None, "pending": []}


def _font(size: int) -> ImageFont.ImageFont:
    for f in FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size)


def _prompt_text(workflow: dict) -> tuple[str, int, int, int]:
    """从工作流里找正向提示词、尺寸和数量。"""
    text, w, h, n = "封面", 768, 1024, 1
    for node in workflow.values():
        inputs = node.get("inputs", {})
        if node.get("class_type") == "CLIPTextEncode" and text == "封面":
            text = str(inputs.get("text", text))
        if node.get("class_type") == "EmptyLatentImage":
            w, h, n = int(inputs.get("width", w)), int(inputs.get("height", h)), int(inputs.get("batch_size", n))
    return text, w, h, n


def _render(text: str, w: int, h: int, idx: int) -> bytes:
    bg, accent = PALETTES[idx % len(PALETTES)]
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(h * 0.62), w, h], fill=accent)
    # 中枢的提示词形如「小红书封面，主文案「xxx」，风格……」，优先取主文案
    m = re.search(r"「(.+?)」", text)
    title = (m.group(1) if m else text.split("，")[0])[:24]
    for i, line in enumerate(textwrap.wrap(title, 8)[:3]):
        d.text((w * 0.08, h * 0.12 + i * w * 0.14), line, font=_font(int(w * 0.1)), fill=(40, 36, 30))
    d.text((w * 0.08, h * 0.68), f"模拟出图 · 第 {idx + 1} 版", font=_font(int(w * 0.045)), fill=(255, 255, 255))
    d.text((w * 0.08, h * 0.93), "MOCK COMFYUI", font=_font(int(w * 0.03)), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


async def _worker() -> None:
    while True:
        prompt_id, workflow = await queue.get()
        state["pending"].remove(prompt_id)
        state["running"] = prompt_id
        await asyncio.sleep(RENDER_SECONDS)
        text, w, h, n = _prompt_text(workflow)
        images = []
        for i in range(n):
            name = f"hub-cover_{prompt_id[:8]}_{i + 1:05d}_.png"
            files[name] = _render(text, w, h, i)
            images.append({"filename": name, "subfolder": "", "type": "output"})
        save_node = next((k for k, v in workflow.items() if v.get("class_type") == "SaveImage"), "9")
        history[prompt_id] = {"prompt": [0, prompt_id, workflow, {}, [save_node]],
                              "outputs": {save_node: {"images": images}},
                              "status": {"status_str": "success", "completed": True, "messages": []}}
        state["running"] = None


@app.on_event("startup")
async def _start() -> None:
    asyncio.create_task(_worker())


@app.post("/prompt")
async def prompt(body: dict):
    workflow = body.get("prompt")
    if not isinstance(workflow, dict):
        raise HTTPException(400, "prompt 缺失")
    prompt_id = str(uuid.uuid4())
    state["pending"].append(prompt_id)
    await queue.put((prompt_id, workflow))
    return {"prompt_id": prompt_id, "number": len(history) + len(state["pending"]), "node_errors": {}}


@app.get("/history/{prompt_id}")
def get_history(prompt_id: str):
    return {prompt_id: history[prompt_id]} if prompt_id in history else {}


@app.get("/view")
def view(filename: str, subfolder: str = "", type: str = "output"):  # noqa: A002 与 ComfyUI 参数名一致
    if filename not in files:
        raise HTTPException(404)
    return Response(files[filename], media_type="image/png")


@app.get("/queue")
def get_queue():
    running = [[0, state["running"]]] if state["running"] else []
    return {"queue_running": running, "queue_pending": [[i, p] for i, p in enumerate(state["pending"])]}


@app.get("/system_stats")
def system_stats():
    busy = state["running"] is not None
    return {"system": {"os": "mock", "comfyui_version": "mock"},
            "devices": [{"name": "Mock GPU（开发用）", "type": "cuda", "index": 0,
                         "vram_total": 24 * 1024**3, "vram_free": (6 if busy else 22) * 1024**3}]}
