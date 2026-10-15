"""中台控制台后端。

运行：uv run uvicorn app.main:app --reload --port 8100
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .providers.base import Provider
from .providers.demo import DemoProvider, NotFound

DATA_MODE = os.getenv("HUB_CONSOLE_MODE", "demo")


def make_provider() -> Provider:
    if DATA_MODE == "demo":
        return DemoProvider()
    raise RuntimeError(f"未实现的数据模式：{DATA_MODE}")


app = FastAPI(title="企业智能体中枢 · 控制台 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("HUB_CONSOLE_CORS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
provider: Provider = make_provider()


@app.exception_handler(NotFound)
async def not_found(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": exc.args[0]})


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


@app.get("/api/overview")
def overview():
    return provider.overview()


@app.get("/api/departments")
def departments():
    return provider.departments()


@app.get("/api/members")
def members(dept: str | None = None, q: str | None = None):
    return provider.members(dept=dept, q=q)


@app.put("/api/members/{member_id}/role-pack")
def assign_role_pack(member_id: str, body: AssignBody):
    return provider.assign_role_pack(member_id, body.role_pack_id)


@app.get("/api/role-packs")
def role_packs():
    return provider.role_packs()


@app.get("/api/role-packs/{role_pack_id}")
def role_pack(role_pack_id: str):
    return provider.role_pack(role_pack_id)


@app.patch("/api/role-packs/{role_pack_id}")
def update_role_pack(role_pack_id: str, body: RolePackPatch):
    if body.monthly_quota is not None and body.monthly_quota < 0:
        raise HTTPException(400, "额度不能为负数")
    return provider.update_role_pack(role_pack_id, body.model_dump(exclude_none=True))


@app.get("/api/catalog")
def catalog():
    return provider.catalog()


@app.get("/api/skills")
def skills():
    return provider.skills()


@app.get("/api/skills/{skill_id}")
def skill(skill_id: str):
    return provider.skill(skill_id)


@app.get("/api/knowledge-bases")
def knowledge_bases():
    return provider.knowledge_bases()


@app.get("/api/knowledge-bases/{kb_id}/documents")
def kb_documents(kb_id: str):
    return provider.kb_documents(kb_id)


@app.get("/api/audit/traces")
def traces(member_id: str | None = None, outcome: str | None = None, dept: str | None = None, q: str | None = None):
    return provider.traces(member_id=member_id, outcome=outcome, dept=dept, q=q)


@app.get("/api/audit/traces/{trace_id}")
def trace(trace_id: str):
    return provider.trace(trace_id)


@app.get("/api/usage")
def usage(days: int = 30):
    return provider.usage(days=max(1, min(days, 30)))
