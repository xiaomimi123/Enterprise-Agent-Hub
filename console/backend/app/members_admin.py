"""成员管理：通过 Casdoor 管理接口创建 / 修改 / 停用 / 删除成员、重置密码、批量导入。

- 身份以 Casdoor 为唯一真相；初始密码由管理员设定或随机生成，首次登录强制修改（needUpdatePassword）
- 停用成员：Casdoor 禁止登录 + 回收他在 New API 的全部 key；已签发的令牌由 accounts.is_active 在 30 秒内拒绝
- 初始密码只在创建 / 重置的响应里出现一次，不写审计、不写日志
"""

from __future__ import annotations

import csv
import io
import re
import secrets
import string

import httpx

from . import accounts
from .config import settings

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,30}$")
CSV_COLUMNS = ("username", "display_name", "dept", "title", "phone", "email", "password")
MAX_IMPORT_ROWS = 500


class MemberError(Exception):
    """参数不合法或操作被拒绝，消息可以直接给管理员看。"""


def check_password(pw: str) -> None:
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise MemberError("密码至少 8 位，且同时包含字母和数字")


def random_password() -> str:
    """10 位，字母 + 数字（去掉易混字符），保证两类都有。"""
    letters, digits = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ", "23456789"
    chars = [secrets.choice(letters), secrets.choice(digits)] + [secrets.choice(letters + digits) for _ in range(8)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


class MemberAdmin:
    def __init__(self, client: httpx.Client | None = None, org: str | None = None, newapi=None):
        self.org = org or settings.casdoor_org
        self.http = client or httpx.Client(base_url=settings.casdoor_endpoint, timeout=15,
                                           auth=(settings.casdoor_client_id, settings.casdoor_client_secret))
        self._newapi = newapi

    # ---- Casdoor ----
    def _call(self, method: str, path: str, **kw) -> object:
        try:
            body = self.http.request(method, path, **kw).json()
        except (httpx.HTTPError, ValueError) as e:
            raise MemberError(f"连接身份服务失败：{e}") from None
        if body.get("status") != "ok":
            raise MemberError(f"身份服务拒绝：{body.get('msg') or '未知错误'}")
        return body.get("data")

    def _groups(self) -> dict[str, str]:
        """部门 id → 显示名。"""
        return {g["name"]: g.get("displayName") or g["name"] for g in (self._call("GET", "/api/get-groups", params={"owner": self.org}) or [])}

    def _resolve_dept(self, dept: str) -> str:
        dept = (dept or "").strip()
        groups = self._groups()
        if dept in groups:
            return dept
        by_display = [k for k, v in groups.items() if v == dept]
        if len(by_display) == 1:
            return by_display[0]
        raise MemberError(f"部门「{dept}」不存在，可选：{'、'.join(groups.values())}")

    def get_user(self, name: str) -> dict:
        u = self._call("GET", "/api/get-user", params={"id": f"{self.org}/{name}"})
        if not u:
            raise MemberError(f"成员 {name} 不存在")
        return u

    def _save(self, user: dict) -> None:
        self._call("POST", "/api/update-user", params={"id": f"{self.org}/{user['name']}"}, json=user)
        accounts.invalidate(self.org, user["name"])

    def _newapi_client(self):
        if self._newapi is None:
            from .newapi import NewApi
            self._newapi = NewApi()
        return self._newapi

    def revoke_keys(self, name: str) -> int:
        """回收这个人的全部模型 key（未配置模型网关时为 0）。"""
        na = self._newapi_client()
        if not na.configured:
            return 0
        return na.delete_tokens_of(self.org, name)

    # ---- 操作 ----
    def create(self, name: str, display_name: str, dept: str, title: str = "", phone: str = "", email: str = "",
               password: str = "") -> dict:
        name = (name or "").strip().lower()
        if not NAME_RE.match(name):
            raise MemberError("用户名只能用小写字母、数字、点、下划线、短横线，2–31 位，且以字母或数字开头")
        if not (display_name or "").strip():
            raise MemberError("请填写姓名")
        password = (password or "").strip() or random_password()
        check_password(password)
        group = self._resolve_dept(dept)
        user = {"owner": self.org, "name": name, "displayName": display_name.strip(), "type": "normal-user",
                "password": password, "groups": [f"{self.org}/{group}"], "title": (title or "").strip(),
                "phone": (phone or "").strip(), "email": (email or "").strip(), "countryCode": "CN",
                "isAdmin": False, "isForbidden": False, "needUpdatePassword": True, "signupApplication": "hub-console"}
        if self._call("GET", "/api/get-user", params={"id": f"{self.org}/{name}"}):
            raise MemberError(f"用户名 {name} 已存在")
        self._call("POST", "/api/add-user", json=user)
        accounts.invalidate(self.org, name)
        return {"id": name, "name": display_name.strip(), "dept": group, "initial_password": password}

    def update(self, name: str, display_name: str | None = None, dept: str | None = None, title: str | None = None,
               phone: str | None = None, email: str | None = None) -> dict:
        u = self.get_user(name)
        if display_name is not None:
            if not display_name.strip():
                raise MemberError("请填写姓名")
            u["displayName"] = display_name.strip()
        if dept is not None:
            u["groups"] = [f"{self.org}/{self._resolve_dept(dept)}"]
        for key, val in (("title", title), ("phone", phone), ("email", email)):
            if val is not None:
                u[key] = val.strip()
        self._save(u)
        return {"id": name}

    def reset_password(self, name: str, password: str = "") -> dict:
        u = self.get_user(name)
        password = (password or "").strip() or random_password()
        check_password(password)
        self._call("POST", "/api/set-password", data={"userOwner": self.org, "userName": name, "newPassword": password})
        u = self.get_user(name)  # set-password 之后重新读取，避免覆盖
        u["needUpdatePassword"] = True
        self._save(u)
        return {"id": name, "initial_password": password}

    def _guard_target(self, u: dict, acting: str, what: str) -> None:
        if u["name"] == acting:
            raise MemberError(f"不能{what}自己的账号")
        if u.get("isAdmin"):
            raise MemberError(f"管理员账号不能{what}，请先在身份服务里取消管理员身份")

    def set_enabled(self, name: str, enabled: bool, acting: str = "") -> dict:
        u = self.get_user(name)
        revoked = 0
        if not enabled:
            self._guard_target(u, acting, "停用")
        u["isForbidden"] = not enabled
        self._save(u)
        if not enabled:
            revoked = self.revoke_keys(name)
        return {"id": name, "enabled": enabled, "revoked_keys": revoked}

    def remove(self, name: str, acting: str = "") -> dict:
        u = self.get_user(name)
        self._guard_target(u, acting, "删除")
        self._call("POST", "/api/delete-user", json={"owner": self.org, "name": name})
        accounts.invalidate(self.org, name)
        return {"id": name, "revoked_keys": self.revoke_keys(name)}

    # ---- 批量导入 ----
    @staticmethod
    def parse_csv(text: str) -> list[dict]:
        rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
        if not rows:
            raise MemberError("没有读到任何成员，请确认第一行是表头：" + ",".join(CSV_COLUMNS))
        if len(rows) > MAX_IMPORT_ROWS:
            raise MemberError(f"一次最多导入 {MAX_IMPORT_ROWS} 人")
        if "username" not in rows[0]:
            raise MemberError("缺少 username 列，表头应为：" + ",".join(CSV_COLUMNS))
        return [{k: (v or "").strip() for k, v in r.items() if k} for r in rows]

    def import_rows(self, rows: list[dict]) -> dict:
        """逐行创建，某一行失败不影响其他行；返回每行结果（成功的带初始密码，仅此一次）。"""
        results = []
        for i, r in enumerate(rows, 2):  # 表头是第 1 行
            try:
                out = self.create(r.get("username", ""), r.get("display_name", ""), r.get("dept", ""), r.get("title", ""),
                                  r.get("phone", ""), r.get("email", ""), r.get("password", ""))
                results.append({"row": i, "username": out["id"], "ok": True, "initial_password": out["initial_password"]})
            except MemberError as e:
                results.append({"row": i, "username": r.get("username", ""), "ok": False, "error": str(e)})
        return {"created": sum(1 for x in results if x["ok"]), "failed": sum(1 for x in results if not x["ok"]), "results": results}
