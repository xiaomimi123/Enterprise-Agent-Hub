"""中台控制台后端。

运行：uv run uvicorn app.main:app --reload --port 8100
"""

from __future__ import annotations

from mimetypes import guess_type

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import agent_api, auth, gpu, model_proxy
from .config import settings
from .providers.base import Provider
from .providers.demo import DemoProvider, NotFound


def make_provider() -> Provider:
    if settings.mode == "demo":
        return DemoProvider()
    if settings.mode == "casdoor":
        from .providers.casdoor import CasdoorProvider
        return CasdoorProvider()
    raise RuntimeError(f"未实现的数据模式：{settings.mode}")


app = FastAPI(title="企业智能体中枢 · 控制台 API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
provider: Provider = make_provider()
app.include_router(auth.router)
app.include_router(agent_api.router)
# 员工模型调用代理（/v1）：不经管理员登录，靠员工专属模型 key 鉴权
app.include_router(model_proxy.router)
# 除健康检查和登录接口外，所有接口都要求管理员登录
api = APIRouter(prefix="/api", dependencies=[Depends(auth.current_user)])


@app.exception_handler(NotFound)
async def not_found(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": exc.args[0]})


@app.exception_handler(RuntimeError)
async def upstream_error(_: Request, exc: RuntimeError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


class AssignBody(BaseModel):
    role_pack_id: str


class RolePackPatch(BaseModel):
    skills: list[str] | None = None
    knowledge_bases: list[str] | None = None
    tools: list[str] | None = None
    models: list[str] | None = None
    monthly_quota: int | None = None
    max_action_level: str | None = None
    external_access: str | None = None
    description: str | None = None
    status: str | None = None


@app.get("/api/health")
def health():
    return {"ok": True, "mode": provider.mode}


@app.get("/api/files/{task_id}/{name}")
def download_file(task_id: str, name: str, exp: int = 0, sig: str = ""):
    """生成结果下载：凭链接里的签名和有效期访问，不需要登录（链接由 MCP 工具发给员工）。

    结果可能是图片（.png）或视频（.mp4），按扩展名给媒体类型，便于浏览器直接播放。
    """
    f = gpu.verify_file(task_id, name, exp, sig)
    if f is None:
        raise HTTPException(404, "链接无效或已过期")
    return FileResponse(f, media_type=guess_type(name)[0] or "application/octet-stream")


# ---- 以下接口需要登录 ----


@api.get("/overview")
def overview():
    return provider.overview()


@api.get("/departments")
def departments():
    return provider.departments()


@api.get("/members")
def members(dept: str | None = None, q: str | None = None):
    return provider.members(dept=dept, q=q)


@api.put("/members/{member_id}/role-pack")
def assign_role_pack(member_id: str, body: AssignBody):
    return provider.assign_role_pack(member_id, body.role_pack_id)


@api.get("/role-packs")
def role_packs():
    return provider.role_packs()


@api.get("/role-packs/{role_pack_id}")
def role_pack(role_pack_id: str):
    return provider.role_pack(role_pack_id)


@api.patch("/role-packs/{role_pack_id}")
def update_role_pack(role_pack_id: str, body: RolePackPatch):
    if body.monthly_quota is not None and body.monthly_quota < 0:
        raise HTTPException(400, "额度不能为负数")
    return provider.update_role_pack(role_pack_id, body.model_dump(exclude_none=True))


@api.get("/catalog")
def catalog():
    return provider.catalog()


@api.get("/skills")
def skills():
    return provider.skills()


@api.get("/skills/{skill_id}")
def skill(skill_id: str):
    return provider.skill(skill_id)


@api.get("/knowledge-bases")
def knowledge_bases():
    return provider.knowledge_bases()


@api.get("/knowledge-bases/{kb_id}/documents")
def kb_documents(kb_id: str):
    return provider.kb_documents(kb_id)


@api.get("/audit/traces")
def traces(member_id: str | None = None, outcome: str | None = None, dept: str | None = None, q: str | None = None):
    return provider.traces(member_id=member_id, outcome=outcome, dept=dept, q=q)


@api.get("/audit/traces/{trace_id}")
def trace(trace_id: str):
    return provider.trace(trace_id)


@api.get("/usage")
def usage(days: int = 30):
    return provider.usage(days=max(1, min(days, 30)))


app.include_router(api)
