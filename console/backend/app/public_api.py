"""对外的图片 / 视频生成 HTTP 接口（/api/v1/*），给员工的脚本或其他系统调用。

- 鉴权：请求头 Authorization: Bearer <Casdoor 令牌>，与 MCP Server 同一套身份和岗位包权限
- 提交只入队，立即返回任务号；用 GET /api/v1/tasks/{id} 轮询，完成后拿到带签名的下载链接
- 追踪 ID：请求头 X-Hub-Trace-Id 可指定，不填则每个任务自成一条链路
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import APIRouter, Header, HTTPException
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


class VideoBody(BaseModel):
    prompt: str
    aspect: str = "9:16"
    seconds: float = Field(4, ge=generation.VIDEO_SECONDS[0], le=generation.VIDEO_SECONDS[1])


def _enqueue(submit, authorization: str | None, trace_id: str | None, **args) -> dict:
    p = _principal(authorization)
    try:
        t = submit(p, (trace_id or "").strip()[:64] or f"api-{uuid.uuid4().hex[:10]}", **args)
    except generation.Busy as e:
        raise HTTPException(429, str(e))
    except generation.Denied as e:
        raise HTTPException(403 if "无权" in str(e) else 400, str(e))
    return {"task_id": t["id"], "status": "排队中", "ahead": t["ahead"], "trace_id": t["trace_id"]}


@router.post("/images", status_code=202)
def create_image(body: ImageBody, authorization: str | None = Header(default=None),
                 x_hub_trace_id: str | None = Header(default=None)):
    return _enqueue(generation.submit_image, authorization, x_hub_trace_id, **body.model_dump())


@router.post("/videos", status_code=202)
def create_video(body: VideoBody, authorization: str | None = Header(default=None),
                 x_hub_trace_id: str | None = Header(default=None)):
    return _enqueue(generation.submit_video, authorization, x_hub_trace_id, **body.model_dump())


@router.get("/tasks/{task_id}")
def get_task(task_id: str, authorization: str | None = Header(default=None)):
    r = generation.get_task(_principal(authorization), task_id)
    if r is None:
        raise HTTPException(404, f"没有找到任务 {task_id}")
    return r
