"""图片 / 视频生成的统一入口：MCP 工具和 HTTP 接口都走这里，共用权限判断、任务队列和审计。

- 权限：岗位包里要有对应工具（image.cover / image.generate / video.generate），且只开放给官方 agent
- 执行：任务写入队列，由调度服务派给 ComfyUI 节点（工作流见 gpu-node/workflows）
- 审计：提交时记一条，完成时由调度服务再记一条，两条共用同一个追踪 ID
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PIL import Image, UnidentifiedImageError

from . import db, gpu, policy
from .config import settings

# 画幅 → 宽高（均为 32 的倍数）。图片按约 0.8 百万像素，视频按约 0.4 百万像素，兼顾速度和清晰度
IMAGE_ASPECTS = {"3:4": (768, 1024), "1:1": (1024, 1024), "4:3": (1024, 768), "9:16": (576, 1024), "16:9": (1024, 576)}
VIDEO_ASPECTS = {"9:16": (480, 832), "16:9": (832, 480), "1:1": (640, 640), "3:4": (576, 768), "4:3": (768, 576)}
MAX_IMAGES = 4
VIDEO_SECONDS = (2, 10)
FPS = 24
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


class Denied(Exception):
    """没有权限或参数不合法，消息可以直接告诉调用方。"""


class QuotaExceeded(Denied):
    """本月 GPU 额度用完了。"""


class Busy(Denied):
    """这个人未完成的任务太多，稍后再提交。"""


def video_frames(seconds: float) -> int:
    """MiniMax-H3 的帧数必须是 17k+5。"""
    n = max(5, round(seconds * FPS))
    return n + (5 - n % 17) % 17


def _audit(p: policy.Principal, trace_id: str, tool: str, detail: str, result: str, task: str = "") -> None:
    db.add_audit(trace_id=trace_id, org=p.org, user_name=p.user_name, display_name=p.display_name, dept=p.dept,
                 channel=p.channel, kind="拦截" if result == "拒绝" else "工具", tool=tool, detail=detail,
                 result=result, summary=task)


def _check(p: policy.Principal, trace_id: str, tool: str, what: str) -> None:
    if p.is_external or not policy.can_use_tool(p, tool):
        _audit(p, trace_id, tool, f"岗位包「{p.pack['name']}」没有{what}的权限", "拒绝")
        raise Denied(f"无权使用{what}。")


def _submit(p: policy.Principal, trace_id: str, tool: str, workflow: str, params: dict, label: str) -> dict:
    limit = settings.gpu_max_pending_per_user
    if limit > 0 and db.pending_task_count(p.org, p.user_name) >= limit:
        _audit(p, trace_id, tool, f"未完成任务已达上限 {limit} 个，{label}未入队", "拒绝")
        raise Busy(f"你还有 {limit} 个生成任务没完成（每人最多同时 {limit} 个），请等完成后再提交。")
    quota = int(p.pack.get("gpu_quota_minutes") or 0)
    if quota > 0 and db.gpu_seconds_this_month(p.org, p.user_name) >= quota * 60:
        _audit(p, trace_id, tool, f"本月 GPU 额度 {quota} 分钟已用完，{label}未入队", "拒绝")
        raise QuotaExceeded(f"本月 GPU 额度（{quota} 分钟）已用完，请联系管理员在岗位包里调整。")
    t = gpu.submit_task(trace_id=trace_id, org=p.org, user_name=p.user_name, display_name=p.display_name, dept=p.dept,
                        channel=p.channel, workflow=workflow, params={**params, "tool": tool})
    _audit(p, trace_id, tool, f"派发{label}，前面排队 {t['ahead']} 个", "通过")
    return t


def submit_cover(p: policy.Principal, trace_id: str, title: str, description: str | None) -> dict:
    _check(p, trace_id, "image.cover", "生成封面图")
    w, h = IMAGE_ASPECTS["3:4"]
    prompt = f"小红书封面，主文案「{title}」，{description or '柔和自然光，干净留白，高级质感'}"
    return _submit(p, trace_id, "image.cover", "image-gen",
                   {"prompt": prompt, "title": title, "width": w, "height": h, "count": 3}, f"封面任务「{title}」")


def submit_image(p: policy.Principal, trace_id: str, prompt: str, aspect: str = "1:1", count: int = 1) -> dict:
    _check(p, trace_id, "image.generate", "文生图")
    if aspect not in IMAGE_ASPECTS:
        raise Denied(f"不支持的画幅 {aspect}，可选：{'、'.join(IMAGE_ASPECTS)}")
    if not prompt.strip():
        raise Denied("提示词不能为空。")
    count = max(1, min(int(count), MAX_IMAGES))
    w, h = IMAGE_ASPECTS[aspect]
    return _submit(p, trace_id, "image.generate", "image-gen",
                   {"prompt": prompt, "title": prompt[:20], "width": w, "height": h, "count": count},
                   f"文生图任务（{aspect}，{count} 张）")


def submit_video(p: policy.Principal, trace_id: str, prompt: str, aspect: str = "9:16", seconds: float = 4) -> dict:
    _check(p, trace_id, "video.generate", "文生视频")
    if aspect not in VIDEO_ASPECTS:
        raise Denied(f"不支持的画幅 {aspect}，可选：{'、'.join(VIDEO_ASPECTS)}")
    if not prompt.strip():
        raise Denied("提示词不能为空。")
    lo, hi = VIDEO_SECONDS
    seconds = max(lo, min(float(seconds), hi))
    w, h = VIDEO_ASPECTS[aspect]
    return _submit(p, trace_id, "video.generate", "video-h3",
                   {"prompt": prompt, "title": prompt[:20], "width": w, "height": h, "length": video_frames(seconds)},
                   f"文生视频任务（{aspect}，约 {seconds:g} 秒）")


def _image_ext(data: bytes) -> str:
    if len(data) > MAX_IMAGE_BYTES:
        raise Denied(f"参考图不能超过 {MAX_IMAGE_BYTES // 1024 // 1024} MB。")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
            fmt = im.format
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise Denied("参考图不是有效的图片，支持 PNG、JPEG、WEBP。")
    if fmt not in IMAGE_FORMATS:
        raise Denied("参考图格式不支持，支持 PNG、JPEG、WEBP。")
    return IMAGE_FORMATS[fmt]


def image_from_hub_url(url: str) -> bytes:
    """只接受中枢自己签发的下载链接（如刚生成的封面），不去抓任意网址，避免被用来探测内网（SSRF）。"""
    parts = urlsplit(url)
    base = urlsplit(settings.public_url)
    segs = parts.path.split("/")
    q = parse_qs(parts.query)
    ok = (parts.scheme, parts.netloc) == (base.scheme, base.netloc) and len(segs) == 5 and segs[1:3] == ["api", "files"]
    f = None
    if ok and q.get("exp") and q.get("sig") and q["exp"][0].isdigit():
        f = gpu.verify_file(segs[3], segs[4], int(q["exp"][0]), q["sig"][0])
    if f is None:
        raise Denied("参考图链接无效：只接受中枢生成的、未过期的图片链接；其他图片请通过上传接口提交。")
    return f.read_bytes()


def submit_video_from_image(p: policy.Principal, trace_id: str, image: bytes, prompt: str, seconds: float = 4) -> dict:
    _check(p, trace_id, "video.generate", "图生视频")
    ext = _image_ext(image)
    if not prompt.strip():
        raise Denied("请描述画面要怎么动（提示词不能为空）。")
    lo, hi = VIDEO_SECONDS
    seconds = max(lo, min(float(seconds), hi))
    rel = f"_inputs/{uuid.uuid4().hex}{ext}"
    dest = Path(settings.outputs_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(image)
    return _submit(p, trace_id, "video.generate", "video-h3-i2v",
                   {"prompt": prompt, "title": prompt[:20], "length": video_frames(seconds), "_input": rel},
                   f"图生视频任务（约 {seconds:g} 秒）")


def get_task(p: policy.Principal, task_id: str) -> dict | None:
    t = db.gpu_task(task_id)
    if not t or t["org"] != p.org or t["user_name"] != p.user_name:
        return None
    return gpu.describe(t)
