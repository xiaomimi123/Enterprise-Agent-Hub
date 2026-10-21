"""控制台「成员」管理接口：创建、修改、重置密码、停用 / 启用、删除、CSV 批量导入。挂在 /api 下，已限定为管理员。

所有操作写审计（kind「配置」）；审计详情和日志里不含任何密码。初始密码只在响应里出现一次。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db
from .config import settings
from .members_admin import MemberAdmin, MemberError

router = APIRouter(prefix="/members", tags=["members"])


def make_admin() -> MemberAdmin:
    return MemberAdmin()


def _audit(user: dict, tool: str, detail: str, result: str = "通过") -> None:
    if not settings.database_url:
        return
    db.add_audit(trace_id="", org=user.get("org") or "", user_name=user.get("name") or "",
                 display_name=user.get("display_name") or "", dept="", channel="控制台", kind="配置", tool=tool,
                 detail=detail, result=result)


def _guard(fn):
    if settings.mode != "casdoor":
        raise HTTPException(400, "演示模式不支持成员管理")
    try:
        return fn()
    except MemberError as e:
        raise HTTPException(400, str(e)) from None


class NewMember(BaseModel):
    username: str
    display_name: str
    dept: str
    title: str = ""
    phone: str = ""
    email: str = ""
    password: str = ""


class MemberPatch(BaseModel):
    display_name: str | None = None
    dept: str | None = None
    title: str | None = None
    phone: str | None = None
    email: str | None = None


class PasswordBody(BaseModel):
    password: str = ""


class EnabledBody(BaseModel):
    enabled: bool


@router.post("")
def create_member(body: NewMember, user: dict = Depends(auth.current_user)):
    out = _guard(lambda: make_admin().create(body.username, body.display_name, body.dept, body.title, body.phone,
                                             body.email, body.password))
    _audit(user, "member.create", f"创建成员 {out['id']}（{out['name']}，部门 {out['dept']}）")
    return out


@router.patch("/{member_id}")
def update_member(member_id: str, body: MemberPatch, user: dict = Depends(auth.current_user)):
    out = _guard(lambda: make_admin().update(member_id, body.display_name, body.dept, body.title, body.phone, body.email))
    changed = [k for k, v in (("姓名", body.display_name), ("部门", body.dept), ("职位", body.title), ("手机", body.phone),
                              ("邮箱", body.email)) if v is not None]
    _audit(user, "member.update", f"修改成员 {member_id}：{'、'.join(changed) or '无变化'}")
    return out


@router.post("/{member_id}/password")
def reset_password(member_id: str, body: PasswordBody, user: dict = Depends(auth.current_user)):
    out = _guard(lambda: make_admin().reset_password(member_id, body.password))
    _audit(user, "member.password", f"重置成员 {member_id} 的密码（首次登录需修改）")
    return out


@router.post("/{member_id}/enabled")
def set_enabled(member_id: str, body: EnabledBody, user: dict = Depends(auth.current_user)):
    out = _guard(lambda: make_admin().set_enabled(member_id, body.enabled, acting=user.get("name") or ""))
    _audit(user, "member.enable" if body.enabled else "member.disable",
           f"{'启用' if body.enabled else '停用'}成员 {member_id}" + (f"，回收 {out['revoked_keys']} 个模型 key" if not body.enabled else ""))
    return out


@router.delete("/{member_id}")
def delete_member(member_id: str, user: dict = Depends(auth.current_user)):
    out = _guard(lambda: make_admin().remove(member_id, acting=user.get("name") or ""))
    if settings.database_url:
        db.drop_user_roles(user.get("org") or "", member_id)  # 删除的人不能再留着老板 / 主管身份
    _audit(user, "member.delete", f"删除成员 {member_id}，回收 {out['revoked_keys']} 个模型 key")
    return out


@router.post("/import")
def import_members(csv_text: str = Body(..., media_type="text/csv"), user: dict = Depends(auth.current_user)):
    """请求体是 CSV 文本，表头：username,display_name,dept,title,phone,email,password（password 留空则随机生成）。"""
    def run():
        admin = make_admin()
        return admin.import_rows(admin.parse_csv(csv_text))
    out = _guard(run)
    _audit(user, "member.import", f"批量导入成员：成功 {out['created']} 人，失败 {out['failed']} 人",
           "通过" if not out["failed"] else "部分失败")
    return out
