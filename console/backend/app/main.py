"""中台控制台后端。

运行：uv run uvicorn app.main:app --reload --port 8100
"""

from __future__ import annotations

import mimetypes
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import agent_api, apps, auth, db, gpu, models_api, public_api
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
app.include_router(public_api.router)
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
    model_mode: str | None = None
    gpu_quota_minutes: int | None = None
    apps: list[str] | None = None


@app.get("/api/health")
def health():
    return {"ok": True, "mode": provider.mode}


@app.get("/api/apps/{app_id}/{filename}")
def download_app(app_id: str, filename: str, exp: int = 0, sig: str = ""):
    """应用包下载：凭 open_app 签发的短期签名链接，不需要登录；校验失败一律 404。"""
    if not filename.endswith(".zip"):
        raise HTTPException(404, "链接无效或已过期")
    f = apps.verify_zip_request(app_id, filename[:-4], exp, sig)
    if f is None:
        raise HTTPException(404, "链接无效或已过期")
    return FileResponse(f, media_type="application/zip", filename=f"{app_id}-{filename}")


@app.get("/api/files/{task_id}/{name}")
def download_file(task_id: str, name: str, exp: int = 0, sig: str = ""):
    """生成结果下载：凭链接里的签名和有效期访问，不需要登录（链接由 MCP 工具发给员工）。"""
    f = gpu.verify_file(task_id, name, exp, sig)
    if f is None:
        raise HTTPException(404, "链接无效或已过期")
    return FileResponse(f, media_type=mimetypes.guess_type(f.name)[0] or "application/octet-stream")


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
    if body.gpu_quota_minutes is not None and body.gpu_quota_minutes < 0:
        raise HTTPException(400, "GPU 额度不能为负数")
    if body.apps is not None and (unknown := [a for a in body.apps if apps.get_app(a) is None]):
        raise HTTPException(400, f"这些应用没有在中枢注册：{'、'.join(unknown)}")
    if body.model_mode is not None and body.model_mode not in ("中枢模型", "自带模型"):
        raise HTTPException(400, "模型方式只能是「中枢模型」或「自带模型」")
    return provider.update_role_pack(role_pack_id, body.model_dump(exclude_none=True))


@api.get("/catalog")
def catalog():
    data = provider.catalog()
    # 模型网关配置了就用真实的：岗位包「可用模型」能勾选的就是管理员接入并启用的模型；网关不可用时保留原清单
    try:
        na = models_api.make_newapi()
        if na.configured:
            data = {**data, "models": [{"id": m, "name": m, "location": "上游", "rate": ""} for m in na.available_models()]}
    except Exception:  # noqa: BLE001
        pass
    return data


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


@api.get("/gpu/tasks")
def gpu_tasks(limit: int = 100):
    if not settings.database_url:  # 演示模式没有任务队列
        return {"summary": {"queued": 0, "running": 0, "failed": 0, "done_today": 0}, "tasks": []}
    return gpu.list_tasks(max(1, min(limit, 200)))


def _app_events(days: int) -> list[dict]:
    """近 N 天与应用相关的审计事件；演示模式没有数据库，返回空。"""
    return [e for e in db.recent_audit(settings.casdoor_org, days) if e["tool"] == "app.open"] if settings.database_url else []


@api.get("/apps")
def list_published_apps():
    """控制台「应用」页：已发布的应用、哈希、哪些岗位包能打开、近 7 天打开次数。"""
    since = datetime.now().astimezone() - timedelta(days=7)
    events = [e for e in _app_events(7) if e["ts"] >= since]
    packs = provider.role_packs()
    out = []
    for a in apps.list_apps():
        mine = [e for e in events if e["result"] == "通过" and f"「{a.name}」" in e["detail"]]
        out.append({
            "id": a.id, "name": a.name, "version": a.version, "description": a.description,
            "sha256": apps.sha256_of(a.zip_path), "size": a.zip_path.stat().st_size, "requires": a.requires,
            "allowed_packs": [{"id": p["id"], "name": p["name"]} for p in packs if a.id in (p.get("apps") or [])],
            "opens_7d": len(mine), "last_open": max((e["ts"] for e in mine), default=None),
        })
    return out


@api.get("/connect")
def connect():
    """控制台「接入方式」页：员工的 agent 怎么连中枢。"""
    return {"hub_url": settings.public_url, "mcp_url": settings.mcp_public_url,
            "api_base": f"{settings.public_url}/api/v1", "script_url": f"{settings.public_url}/api/agent/hub_agent.py"}


@api.get("/usage")
def usage(days: int = 30):
    return provider.usage(days=max(1, min(days, 30)))


api.include_router(models_api.router)
app.include_router(api)
