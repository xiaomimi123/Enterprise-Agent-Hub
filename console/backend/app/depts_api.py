"""控制台「部门与角色」：部门（Casdoor 分组）的增删改、主管、默认岗位包，以及老板名单。全部只有管理员能用。

- 部门的 id 是 Casdoor 分组名（英文小写），显示名是中文；新建时 id 自动生成，管理员只填中文名
- 主管：每个部门一个或多个，只能看和管自己的部门；老板：看全公司
- 默认岗位包：没有单独分配岗位包的成员，按所在部门的默认岗位包走（没配置时用内置的映射）
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import auth, db, policy
from .config import settings
from .members_admin import MemberAdmin, MemberError

router = APIRouter(prefix="/org", tags=["org"], dependencies=[Depends(auth.current_user)])

DEPT_NAME_MAX = 20


def _need_casdoor() -> None:
    if settings.mode != "casdoor":
        raise HTTPException(400, "演示模式不支持部门与角色管理")


def _audit(user: dict, tool: str, detail: str) -> None:
    db.add_audit(trace_id="", org=user.get("org") or "", user_name=user.get("name") or "", display_name=user.get("display_name") or "",
                 dept="", channel="控制台", kind="配置", tool=tool, detail=detail, result="通过")


def _users(admin: MemberAdmin) -> list[dict]:
    users = admin._call("GET", "/api/get-users", params={"owner": admin.org}) or []
    return [u for u in users if not u.get("isDeleted")]


def _groups(admin: MemberAdmin) -> list[dict]:
    return admin._call("GET", "/api/get-groups", params={"owner": admin.org}) or []


def _dept_of(u: dict) -> str:
    return next((g.split("/", 1)[-1] for g in (u.get("groups") or [])), "")


def _ensure_users(admin: MemberAdmin, names: list[str]) -> list[str]:
    known = {u["name"] for u in _users(admin)}
    names = [n.strip() for n in names if n and n.strip()]
    if unknown := [n for n in names if n not in known]:
        raise HTTPException(400, f"这些成员不存在：{'、'.join(unknown)}")
    return list(dict.fromkeys(names))


@router.get("")
def overview():
    """部门列表（含成员数、主管、默认岗位包）和老板名单。"""
    _need_casdoor()
    admin = MemberAdmin()
    groups, users = _groups(admin), _users(admin)
    roles = db.console_roles(admin.org)
    defaults = db.dept_defaults(admin.org)
    packs = {p["id"]: p["name"] for p in db.role_packs()}
    out = []
    for g in groups:
        gid = g["name"]
        configured = defaults.get(gid)
        effective = policy.default_pack_id(gid, defaults)
        out.append({"id": gid, "name": g.get("displayName") or gid,
                    "member_count": sum(1 for u in users if _dept_of(u) == gid),
                    "managers": [r["user_name"] for r in roles if r["role"] == "manager" and r["dept_id"] == gid],
                    "default_pack": configured, "effective_pack": effective, "effective_pack_name": packs.get(effective, effective)})
    out.sort(key=lambda d: (-d["member_count"], d["name"]))
    return {"departments": out, "bosses": [r["user_name"] for r in roles if r["role"] == "boss"],
            "members": sorted(({"id": u["name"], "name": u.get("displayName") or u["name"]} for u in users), key=lambda m: m["name"]),
            "role_packs": [{"id": k, "name": v} for k, v in packs.items()]}


class DeptBody(BaseModel):
    name: str


def _clean_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > DEPT_NAME_MAX:
        raise HTTPException(400, f"部门名称要 1–{DEPT_NAME_MAX} 个字")
    return name


@router.post("/departments")
def create_department(body: DeptBody, user: dict = Depends(auth.current_user)):
    _need_casdoor()
    name = _clean_name(body.name)
    admin = MemberAdmin()
    if any((g.get("displayName") or g["name"]) == name for g in _groups(admin)):
        raise HTTPException(400, f"部门「{name}」已经存在")
    gid = f"d{secrets.token_hex(4)}"
    try:
        admin._call("POST", "/api/add-group", json={"owner": admin.org, "name": gid, "displayName": name, "type": "Physical",
                                                    "parentId": admin.org, "isTopGroup": True, "isEnabled": True})
    except MemberError as e:
        raise HTTPException(400, str(e)) from None
    _audit(user, "dept.create", f"新建部门「{name}」（{gid}）")
    return {"id": gid, "name": name}


def _find_group(admin: MemberAdmin, dept_id: str) -> dict:
    g = next((x for x in _groups(admin) if x["name"] == dept_id), None)
    if not g:
        raise HTTPException(404, "部门不存在")
    return g


@router.patch("/departments/{dept_id}")
def rename_department(dept_id: str, body: DeptBody, user: dict = Depends(auth.current_user)):
    _need_casdoor()
    name = _clean_name(body.name)
    admin = MemberAdmin()
    g = _find_group(admin, dept_id)
    if any(x["name"] != dept_id and (x.get("displayName") or x["name"]) == name for x in _groups(admin)):
        raise HTTPException(400, f"部门「{name}」已经存在")
    old = g.get("displayName") or dept_id
    try:
        admin._call("POST", "/api/update-group", params={"id": f"{admin.org}/{dept_id}"}, json={**g, "displayName": name})
    except MemberError as e:
        raise HTTPException(400, str(e)) from None
    _audit(user, "dept.rename", f"部门「{old}」改名为「{name}」")
    return {"id": dept_id, "name": name}


@router.delete("/departments/{dept_id}")
def delete_department(dept_id: str, user: dict = Depends(auth.current_user)):
    _need_casdoor()
    admin = MemberAdmin()
    g = _find_group(admin, dept_id)
    in_dept = [u["name"] for u in _users(admin) if _dept_of(u) == dept_id]
    if in_dept:
        raise HTTPException(400, f"部门里还有 {len(in_dept)} 个成员，请先把他们调到别的部门")
    try:
        admin._call("POST", "/api/delete-group", json=g)
    except MemberError as e:
        raise HTTPException(400, str(e)) from None
    db.set_dept_managers(admin.org, dept_id, [])
    db.set_dept_default(admin.org, dept_id, None)
    _audit(user, "dept.delete", f"删除部门「{g.get('displayName') or dept_id}」")
    return {"ok": True}


class UsersBody(BaseModel):
    users: list[str]


@router.put("/departments/{dept_id}/managers")
def set_managers(dept_id: str, body: UsersBody, user: dict = Depends(auth.current_user)):
    _need_casdoor()
    admin = MemberAdmin()
    _find_group(admin, dept_id)
    users = _ensure_users(admin, body.users)
    db.set_dept_managers(admin.org, dept_id, users)
    _audit(user, "role.managers", f"设置部门 {dept_id} 的主管：{'、'.join(users) or '（清空）'}")
    return {"managers": users}


@router.put("/bosses")
def set_bosses(body: UsersBody, user: dict = Depends(auth.current_user)):
    _need_casdoor()
    admin = MemberAdmin()
    users = _ensure_users(admin, body.users)
    db.set_bosses(admin.org, users)
    _audit(user, "role.bosses", f"设置老板名单：{'、'.join(users) or '（清空）'}")
    return {"bosses": users}


class PackBody(BaseModel):
    role_pack_id: str | None = None


@router.put("/departments/{dept_id}/default-pack")
def set_default_pack(dept_id: str, body: PackBody, user: dict = Depends(auth.current_user)):
    _need_casdoor()
    admin = MemberAdmin()
    _find_group(admin, dept_id)
    if body.role_pack_id and body.role_pack_id not in {p["id"] for p in db.role_packs()}:
        raise HTTPException(400, "岗位包不存在")
    db.set_dept_default(admin.org, dept_id, body.role_pack_id)
    _audit(user, "dept.default_pack", f"部门 {dept_id} 的默认岗位包：{body.role_pack_id or '恢复内置映射'}")
    return {"default_pack": body.role_pack_id}
