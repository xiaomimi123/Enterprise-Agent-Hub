"""控制台「技能库」的编辑接口：修改、新建、回滚、审核、版本历史。权限规则见 skillstore.plan_for。

路由挂在 /api 下，经过 auth.console_user（老板和部门主管只能用白名单里的接口）；具体能不能改某个技能由这里按角色判断。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db, skillstore
from .config import settings
from .skillstore import Conflict, SkillError

router = APIRouter(tags=["skills"])


def _need_db() -> None:
    if not settings.database_url:
        raise HTTPException(400, "演示模式不支持编辑技能")


def _audit(user: dict, tool: str, detail: str) -> None:
    db.add_audit(trace_id="", org=user.get("org") or "", user_name=user.get("name") or "", display_name=user.get("display_name") or "",
                 dept="", channel="控制台", kind="配置", tool=tool, detail=detail, result="通过")


def _depts() -> tuple[dict[str, str], set[str]]:
    from .main import provider  # 延迟导入：main 导入了本模块
    names = {d["id"]: d["name"] for d in provider.departments() if d["id"] != "unassigned"}
    return names, set(names)


def _run(fn):
    try:
        return fn()
    except Conflict as e:
        raise HTTPException(409, str(e)) from None
    except SkillError as e:
        raise HTTPException(400, str(e)) from None


class SaveBody(BaseModel):
    content: str
    note: str = ""
    base_version: int | None = None


class CreateBody(BaseModel):
    id: str
    dept: str
    content: str
    note: str = ""


class RollbackBody(BaseModel):
    version: int
    note: str = ""


class ReviewBody(BaseModel):
    approve: bool
    note: str = ""


def _result_text(r: dict) -> str:
    return f"第 {r['version']} 版" + ("，已生效" if r["status"] == "published" else "，已提交审核")


@router.get("/skills/{skill_id}/history")
def history(skill_id: str, user: dict = Depends(auth.console_user)):
    _need_db()
    row = skillstore.get_skill(skill_id)
    if row is None:
        raise HTTPException(404, "技能不存在（还没有导入到版本库）")
    if row["dept_id"] != skillstore.ALL and not (user["depts"] is None or row["dept_id"] in user["depts"]):
        raise HTTPException(403, "你只能查看自己部门和全公司的技能")
    names, _ = _depts()
    vs = skillstore.versions(skill_id)
    return {"skill": {"id": row["id"], "name": row["name"], "dept": row["dept_id"], "dept_name": "全公司" if row["dept_id"] == skillstore.ALL else names.get(row["dept_id"], row["dept_id"]),
                      "published_version": row["published_version"]},
            "mode": skillstore.plan_for(user, row["dept_id"]), "can_review": skillstore.can_review(user),
            "versions": [{"version": v["version"], "author": v["author"], "author_name": v["author_name"], "note": v["note"], "status": v["status"],
                          "reviewer": v["reviewer"], "review_note": v["review_note"], "created_at": v["created_at"].isoformat(),
                          "reviewed_at": v["reviewed_at"].isoformat() if v["reviewed_at"] else None, "content": v["content"]} for v in vs]}


@router.put("/skills/{skill_id}")
def save(skill_id: str, body: SaveBody, user: dict = Depends(auth.console_user)):
    _need_db()
    r = _run(lambda: skillstore.save(skill_id, user, user, body.content, body.note, body.base_version))
    _audit(user, "skill.edit", f"修改技能「{skill_id}」：{_result_text(r)}" + (f"（{body.note.strip()[:60]}）" if body.note.strip() else ""))
    return r


@router.post("/skills")
def create(body: CreateBody, user: dict = Depends(auth.console_user)):
    _need_db()
    _, valid = _depts()
    r = _run(lambda: skillstore.create(body.id.strip(), body.dept, user, user, body.content, body.note, valid))
    _audit(user, "skill.create", f"新建技能「{body.id}」（部门 {body.dept}）：{_result_text(r)}")
    return r


@router.post("/skills/{skill_id}/rollback")
def rollback(skill_id: str, body: RollbackBody, user: dict = Depends(auth.console_user)):
    _need_db()
    r = _run(lambda: skillstore.rollback(skill_id, user, user, body.version, body.note))
    _audit(user, "skill.rollback", f"技能「{skill_id}」回滚到第 {body.version} 版：{_result_text(r)}")
    return r


@router.get("/skill-reviews")
def reviews(user: dict = Depends(auth.console_user)):
    """待审核的修改：老板 / 管理员看全部，主管看自己提交的。"""
    _need_db()
    names, _ = _depts()
    return [{"skill_id": r["skill_id"], "skill_name": r["skill_name"], "version": r["version"], "dept": r["dept_id"],
             "dept_name": "全公司" if r["dept_id"] == skillstore.ALL else names.get(r["dept_id"], r["dept_id"]),
             "author_name": r["author_name"], "note": r["note"], "created_at": r["created_at"].isoformat(),
             "published_version": r["published_version"], "content": r["content"]} for r in skillstore.pending(user, user["name"])]


@router.post("/skill-reviews/{skill_id}/{version}")
def review(skill_id: str, version: int, body: ReviewBody, user: dict = Depends(auth.console_user)):
    _need_db()
    r = _run(lambda: skillstore.review(skill_id, version, user, user, body.approve, body.note))
    _audit(user, "skill.review", f"{'通过' if body.approve else '驳回'}技能「{skill_id}」第 {version} 版的修改")
    return r
