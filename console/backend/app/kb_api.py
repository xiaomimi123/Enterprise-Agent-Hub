"""控制台「知识库」的文档接口：查看、新建、修改、删除、回滚、审核、版本历史。权限规则见 kbstore（同技能库）。

路由挂在 /api 下，经过 auth.console_user（老板和部门主管只能用白名单里的接口）；具体能不能改某个知识库由这里按角色判断。
发布后自动同步到 RAGFlow 检索索引；同步失败不影响文档已保存，列表里显示「待同步」，可以重试。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db, kbstore, skillstore
from .config import settings
from .content import KB_REGISTRY
from .kbstore import KbError
from .ragflow import from_settings
from .skillstore import Conflict, SkillError

router = APIRouter(tags=["knowledge"])


def _need_db() -> None:
    if not settings.database_url:
        raise HTTPException(400, "演示模式不支持编辑知识库")


def _audit(user: dict, tool: str, detail: str) -> None:
    db.add_audit(trace_id="", org=user.get("org") or "", user_name=user.get("name") or "", display_name=user.get("display_name") or "",
                 dept="", channel="控制台", kind="配置", tool=tool, detail=detail, result="通过")


def _kb(kb_id: str, user: dict) -> dict:
    kb = KB_REGISTRY.get(kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    if kb["dept"] != skillstore.ALL and not (user["depts"] is None or kb["dept"] in user["depts"]):
        raise HTTPException(403, "你只能查看自己部门和全公司的知识库")
    return kb


def _dept_name(dept: str) -> str:
    from .main import provider  # 延迟导入：main 导入了本模块
    return "全公司" if dept == skillstore.ALL else provider.d["dept_names"].get(dept, dept)


def _run(fn):
    try:
        return fn()
    except Conflict as e:
        raise HTTPException(409, str(e)) from None
    except SkillError as e:
        raise HTTPException(400, str(e)) from None


def _after(kb_id: str, name: str, r: dict) -> dict:
    """发布后同步到 RAGFlow；返回里带上 synced（没配置 RAGFlow 时为 None）。"""
    r["synced"] = None
    client = from_settings()
    if r.get("published") and client is not None:
        r["synced"] = kbstore.sync_doc(client, kb_id, name)
    return r


def _text(r: dict, what: str) -> str:
    return f"第 {r['version']} 版" + ("，已生效" if r["status"] == "published" else "，已提交审核") + ("" if r.get("synced") in (None, True) else "（索引同步失败，稍后重试）") + f" · {what}"


class SaveBody(BaseModel):
    content: str
    note: str = ""
    base_version: int | None = None


class CreateBody(BaseModel):
    name: str
    content: str
    note: str = ""


class RollbackBody(BaseModel):
    version: int
    note: str = ""


class ReviewBody(BaseModel):
    approve: bool
    note: str = ""


def _version_json(v: dict) -> dict:
    return {"version": v["version"], "author": v["author"], "author_name": v["author_name"], "note": v["note"], "status": v["status"], "is_delete": v["is_delete"],
            "reviewer": v["reviewer"], "review_note": v["review_note"], "created_at": v["created_at"].isoformat(),
            "reviewed_at": v["reviewed_at"].isoformat() if v["reviewed_at"] else None, "content": v["content"]}


@router.get("/knowledge-bases/{kb_id}/documents/{name}")
def document(kb_id: str, name: str, user: dict = Depends(auth.console_user)):
    _need_db()
    kb = _kb(kb_id, user)
    name = _run(lambda: kbstore.clean_name(name))
    row = kbstore.get_doc(kb_id, name)
    if row is None:
        raise HTTPException(404, "文档不存在")
    vs = kbstore.versions(kb_id, name)
    return {"kb": {"id": kb_id, "name": kb["name"], "dept": kb["dept"], "dept_name": _dept_name(kb["dept"])},
            "name": name, "deleted": row["deleted"], "published_version": row["published_version"],
            "mode": skillstore.plan_for(user, kb["dept"]), "can_review": skillstore.can_review(user),
            "content": next((v["content"] for v in vs if v["version"] == row["published_version"]), ""),
            "versions": [_version_json(v) for v in vs]}


@router.get("/knowledge-bases/{kb_id}/deleted")
def deleted_documents(kb_id: str, user: dict = Depends(auth.console_user)):
    """已删除的文档（可以在历史里回滚找回）。"""
    _need_db()
    _kb(kb_id, user)
    with db.connect() as conn:
        rows = conn.execute("SELECT name, updated_at FROM kb_docs WHERE kb_id = %s AND deleted ORDER BY updated_at DESC", (kb_id,)).fetchall()
    return [{"name": r["name"], "updated_at": r["updated_at"].isoformat()} for r in rows]


@router.post("/knowledge-bases/{kb_id}/documents")
def create(kb_id: str, body: CreateBody, user: dict = Depends(auth.console_user)):
    _need_db()
    _kb(kb_id, user)
    r = _run(lambda: kbstore.create(kb_id, body.name, user, user, body.content, body.note))
    name = kbstore.clean_name(body.name)
    r = _after(kb_id, name, r)
    _audit(user, "kb.create", f"知识库「{KB_REGISTRY[kb_id]['name']}」新建文档「{name}」：{_text(r, '新建')}")
    return r


@router.put("/knowledge-bases/{kb_id}/documents/{name}")
def save(kb_id: str, name: str, body: SaveBody, user: dict = Depends(auth.console_user)):
    _need_db()
    _kb(kb_id, user)
    name = _run(lambda: kbstore.clean_name(name))
    r = _after(kb_id, name, _run(lambda: kbstore.save(kb_id, name, user, user, body.content, body.note, body.base_version)))
    _audit(user, "kb.edit", f"知识库「{KB_REGISTRY[kb_id]['name']}」修改文档「{name}」：{_text(r, body.note.strip()[:60] or '修改')}")
    return r


@router.delete("/knowledge-bases/{kb_id}/documents/{name}")
def delete(kb_id: str, name: str, note: str = "", user: dict = Depends(auth.console_user)):
    _need_db()
    _kb(kb_id, user)
    name = _run(lambda: kbstore.clean_name(name))
    r = _after(kb_id, name, _run(lambda: kbstore.delete(kb_id, name, user, user, note)))
    _audit(user, "kb.delete", f"知识库「{KB_REGISTRY[kb_id]['name']}」删除文档「{name}」：{_text(r, '删除')}")
    return r


@router.post("/knowledge-bases/{kb_id}/documents/{name}/rollback")
def rollback(kb_id: str, name: str, body: RollbackBody, user: dict = Depends(auth.console_user)):
    _need_db()
    _kb(kb_id, user)
    name = _run(lambda: kbstore.clean_name(name))
    r = _after(kb_id, name, _run(lambda: kbstore.rollback(kb_id, name, user, user, body.version, body.note)))
    _audit(user, "kb.rollback", f"知识库「{KB_REGISTRY[kb_id]['name']}」文档「{name}」回滚到第 {body.version} 版：{_text(r, '回滚')}")
    return r


@router.post("/knowledge-bases/{kb_id}/sync")
def resync(kb_id: str, user: dict = Depends(auth.console_user)):
    """重试把还没同步到检索索引的文档同步过去。"""
    _need_db()
    kb = _kb(kb_id, user)
    if skillstore.plan_for(user, kb["dept"]) is None:
        raise HTTPException(403, "你没有这个知识库的权限")
    client = from_settings()
    if client is None:
        return {"synced": 0, "failed": 0}
    todo = kbstore.unsynced(kb_id)
    ok = sum(kbstore.sync_doc(client, kb_id, d["name"]) for d in todo)
    return {"synced": ok, "failed": len(todo) - ok}


@router.get("/kb-reviews")
def reviews(user: dict = Depends(auth.console_user)):
    _need_db()
    out = []
    for r in kbstore.pending(user, user["name"]):
        kb = KB_REGISTRY.get(r["kb_id"])
        if not kb or (kb["dept"] != skillstore.ALL and not (user["depts"] is None or kb["dept"] in user["depts"])):
            continue
        out.append({"kb_id": r["kb_id"], "kb_name": kb["name"], "name": r["name"], "version": r["version"], "is_delete": r["is_delete"],
                    "author_name": r["author_name"], "note": r["note"], "created_at": r["created_at"].isoformat(),
                    "published_version": r["published_version"], "content": r["content"]})
    return out


@router.post("/kb-reviews/{kb_id}/{name}/{version}")
def review(kb_id: str, name: str, version: int, body: ReviewBody, user: dict = Depends(auth.console_user)):
    _need_db()
    _kb(kb_id, user)
    name = _run(lambda: kbstore.clean_name(name))
    r = _after(kb_id, name, _run(lambda: kbstore.review(kb_id, name, version, user, user, body.approve, body.note)))
    _audit(user, "kb.review", f"{'通过' if body.approve else '驳回'}知识库「{KB_REGISTRY[kb_id]['name']}」文档「{name}」第 {version} 版的修改")
    return r
