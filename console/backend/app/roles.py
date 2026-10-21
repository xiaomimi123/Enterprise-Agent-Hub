"""控制台角色：谁能进控制台、能看哪些部门。

- 管理员：Casdoor 的 isAdmin，什么都能做（成员、模型、配置……）；
- 老板：看全公司，不改系统配置（技能的改写权限在技能库那一期加上）；
- 部门主管：只能看和管自己负责的部门；一个人可以管多个部门。
员工没有这三种身份就进不了控制台。老板 / 主管的名单存在 console_roles 表，由管理员在「部门与角色」页维护。
"""

from __future__ import annotations

from . import db
from .config import settings

ADMIN, BOSS, MANAGER = "admin", "boss", "manager"


def resolve(org: str, user_name: str, is_admin: bool = False) -> dict:
    """返回 {role, depts}：role 为 admin / boss / manager / None；depts 是主管负责的部门（管理员和老板为 None，表示全部）。"""
    if is_admin:
        return {"role": ADMIN, "depts": None}
    rows = db.roles_of(org, user_name) if settings.database_url else []
    if any(r["role"] == BOSS for r in rows):
        return {"role": BOSS, "depts": None}
    depts = sorted({r["dept_id"] for r in rows if r["role"] == MANAGER and r["dept_id"]})
    return {"role": MANAGER, "depts": depts} if depts else {"role": None, "depts": []}


def can_see_dept(scope: dict, dept: str) -> bool:
    return scope["depts"] is None or dept in scope["depts"]
