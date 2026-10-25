"""对外的图片 / 视频生成 HTTP 接口（/api/v1/*），给员工的脚本或其他系统调用。

- 鉴权：请求头 Authorization: Bearer <Casdoor 令牌>，与 MCP Server 同一套身份和岗位包权限
- 提交只入队，立即返回任务号；用 GET /api/v1/tasks/{id} 轮询，完成后拿到带签名的下载链接
- 追踪 ID：请求头 X-Hub-Trace-Id 可指定，不填则每个任务自成一条链路
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import generation, gpu, policy
from .auth import _jwks_client
from .config import settings

router = APIRouter(prefix="/api/v1", tags=["generate"])


def _principal(authorization: str | None) -> policy.Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "未登录")
    audiences = [*settings.agent_client_ids, *settings.external_client_ids]
    try:
        tok = authorization.split(" ", 1)[1]
        key = _jwks_client().get_signing_key_from_jwt(tok)
        claims = jwt.decode(tok, key.key, algorithms=["RS256"], audience=audiences, options={"verify_iss": False})
    except jwt.PyJWTError:
        raise HTTPException(401, "令牌无效或已过期")
    if claims.get("owner") != settings.casdoor_org:
        raise HTTPException(403, "不属于本企业组织")
    aud = claims.get("aud")
    client_id = next((a for a in (aud if isinstance(aud, list) else [aud]) if a in audiences), "")
    channel = policy.OFFICIAL if client_id in settings.agent_client_ids else policy.EXTERNAL
    p = policy.Principal(org=claims["owner"], user_name=claims["name"],
                         display_name=claims.get("displayName") or claims["name"],
                         dept=policy.dept_from_groups(claims.get("groups")), channel=channel)
    p.pack = policy.resolve_pack(p.org, p.user_name, p.dept)
    return p


class ImageBody(BaseModel):
    prompt: str
    aspect: str = "1:1"
    count: int = Field(1, ge=1, le=generation.MAX_IMAGES)


class CoverBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=40)
    description: str | None = Field(None, max_length=500)


class VideoBody(BaseModel):
    prompt: str
    aspect: str = "9:16"
    seconds: float = Field(4, ge=generation.VIDEO_SECONDS[0], le=generation.VIDEO_SECONDS[1])


def _enqueue(submit, authorization: str | None, trace_id: str | None, **args) -> dict:
    p = _principal(authorization)
    try:
        t = submit(p, (trace_id or "").strip()[:64] or f"api-{uuid.uuid4().hex[:10]}", **args)
    except generation.QuotaExceeded as e:
        raise HTTPException(403, str(e))
    except generation.Busy as e:
        raise HTTPException(429, str(e))
    except generation.Denied as e:
        raise HTTPException(403 if "无权" in str(e) else 400, str(e))
    return {"task_id": t["id"], "status": "排队中", "ahead": t["ahead"], "trace_id": t["trace_id"]}


@router.post("/images", status_code=202)
def create_image(body: ImageBody, authorization: str | None = Header(default=None),
                 x_hub_trace_id: str | None = Header(default=None)):
    return _enqueue(generation.submit_image, authorization, x_hub_trace_id, **body.model_dump())


@router.get("/capabilities")
def get_capabilities(authorization: str | None = Header(default=None)):
    """现在出图 / 出视频走哪条通道、出图能不能带参考图。"""
    _principal(authorization)
    return generation.capabilities()


@router.post("/images/with-references", status_code=202)
async def create_image_with_references(images: list[UploadFile] = File(...), prompt: str = Form(...),
                                       aspect: str = Form("1:1"), count: int = Form(1),
                                       authorization: str | None = Header(default=None),
                                       x_hub_trace_id: str | None = Header(default=None)):
    """参考图生图：上传 1–4 张参考图（PNG / JPEG / WEBP，每张 ≤ 10MB）。只有出图通道是第三方 API 时可用，否则 400。"""
    if len(images) > generation.MAX_REFERENCES:
        raise HTTPException(400, f"参考图最多 {generation.MAX_REFERENCES} 张。")
    refs = [await f.read(generation.MAX_IMAGE_BYTES + 1) for f in images]
    return _enqueue(generation.submit_image, authorization, x_hub_trace_id, prompt=prompt, aspect=aspect,
                    count=max(1, min(count, generation.MAX_IMAGES)), references=refs)


@router.post("/covers", status_code=202)
def create_cover(body: CoverBody, authorization: str | None = Header(default=None),
                 x_hub_trace_id: str | None = Header(default=None)):
    """小红书封面（与 MCP 的 generate_cover 相同：3:4，一次 3 版）。"""
    return _enqueue(generation.submit_cover, authorization, x_hub_trace_id, title=body.title, description=body.description)


@router.post("/videos", status_code=202)
def create_video(body: VideoBody, authorization: str | None = Header(default=None),
                 x_hub_trace_id: str | None = Header(default=None)):
    return _enqueue(generation.submit_video, authorization, x_hub_trace_id, **body.model_dump())


@router.post("/videos/from-image", status_code=202)
async def create_video_from_image(image: UploadFile = File(...), prompt: str = Form(...), seconds: float = Form(4),
                                  authorization: str | None = Header(default=None),
                                  x_hub_trace_id: str | None = Header(default=None)):
    """图生视频：上传参考图（PNG / JPEG / WEBP，≤ 10MB）作为首帧，画幅跟随参考图。"""
    data = await image.read(generation.MAX_IMAGE_BYTES + 1)
    return _enqueue(generation.submit_video_from_image, authorization, x_hub_trace_id, image=data, prompt=prompt,
                    seconds=max(generation.VIDEO_SECONDS[0], min(seconds, generation.VIDEO_SECONDS[1])))


@router.get("/tasks/{task_id}")
def get_task(task_id: str, authorization: str | None = Header(default=None)):
    r = generation.get_task(_principal(authorization), task_id)
    if r is None:
        raise HTTPException(404, f"没有找到任务 {task_id}")
    return r
