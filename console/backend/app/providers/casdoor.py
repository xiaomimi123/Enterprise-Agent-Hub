"""Casdoor 数据源：成员与组织来自 Casdoor（生产环境由钉钉同步进 Casdoor），其余模块暂用演示数据。

- 部门 = Casdoor 组织下的分组（group）
- 成员 = Casdoor 组织下的用户；成员的岗位包存在用户属性 properties.hub_role_pack，
  没设置时按部门的默认岗位包（DEFAULT_ROLE_PACKS），都没有时用「通用办公」
- 读取结果缓存 30 秒，修改岗位包后立即刷新
"""

from __future__ import annotations

import time

import httpx

from ..config import settings
from .demo import DemoProvider, NotFound

ROLE_PACK_PROP = "hub_role_pack"
FALLBACK_ROLE_PACK = "rp-general"
UNASSIGNED = "unassigned"

# 部门（Casdoor 分组名）→ 默认岗位包。真实客户的分组名不同，按实际情况调整
DEFAULT_ROLE_PACKS = {
    "ops": "rp-xhs-ops", "design": "rp-designer", "video": "rp-video", "sales": "rp-sales",
    "cs": "rp-cs", "finance": "rp-finance", "hr": "rp-hr", "tech": "rp-general", "ceo": "rp-general",
}


class CasdoorProvider(DemoProvider):
    mode = "casdoor"
    cache_seconds = 30

    def __init__(self) -> None:
        super().__init__()
        self.org = settings.casdoor_org
        self.http = httpx.Client(
            base_url=settings.casdoor_endpoint,
            auth=(settings.casdoor_client_id, settings.casdoor_client_secret),
            timeout=10,
        )
        self._synced_at = 0.0
        self._users: dict[str, dict] = {}

    # ---- Casdoor API ----
    def _get(self, path: str, **params) -> object:
        body = self.http.get(path, params=params).json()
        if body.get("status") != "ok":
            raise RuntimeError(f"Casdoor {path} 失败：{body.get('msg')}")
        return body.get("data")

    def _sync(self, force: bool = False) -> None:
        """从 Casdoor 拉取部门和成员，替换演示数据里的组织部分。"""
        if not force and time.time() - self._synced_at < self.cache_seconds:
            return
        org = self._get("/api/get-organization", id=f"admin/{self.org}") or {}
        groups = self._get("/api/get-groups", owner=self.org) or []
        users = [u for u in (self._get("/api/get-users", owner=self.org) or []) if not u.get("isDeleted")]

        dept_names = {g["name"]: g.get("displayName") or g["name"] for g in groups}
        dept_names[UNASSIGNED] = "未分配部门"
        dept_names["all"] = "全公司"
        packs = {rp["id"] for rp in self.d["role_packs"]}

        members = []
        for u in users:
            group = next((g.split("/", 1)[-1] for g in (u.get("groups") or []) if g.split("/", 1)[-1] in dept_names), UNASSIGNED)
            default_pack = DEFAULT_ROLE_PACKS.get(group, FALLBACK_ROLE_PACK)
            pack = (u.get("properties") or {}).get(ROLE_PACK_PROP)
            members.append({
                "id": u["name"],
                "name": u.get("displayName") or u["name"],
                "dept": group,
                "dept_name": dept_names[group],
                "title": u.get("title") or "",
                "role_pack": pack if pack in packs else default_pack,
                # 员工端 agent 还没有接入中枢，暂时都显示未安装
                "agent_status": "未安装",
                "agent_version": "",
                "os": "",
                "dingtalk_bound": bool(u.get("dingtalk")),
                "last_active": u.get("lastSigninTime") or u.get("createdTime"),
            })

        departments = []
        for g in [*groups, {"name": UNASSIGNED}]:
            dm = [m for m in members if m["dept"] == g["name"]]
            if g["name"] == UNASSIGNED and not dm:
                continue
            departments.append({
                "id": g["name"], "name": dept_names[g["name"]], "member_count": len(dm),
                "leader": dm[0]["name"] if dm else "", "online": sum(1 for m in dm if m["agent_status"] == "在线"),
                "role_pack": DEFAULT_ROLE_PACKS.get(g["name"], FALLBACK_ROLE_PACK),
            })

        departments.sort(key=lambda x: (x["id"] == UNASSIGNED, -x["member_count"], x["name"]))
        self.d.update({
            "company": org.get("displayName") or self.org,
            "dept_names": dept_names,
            "members": members,
            "departments": departments,
        })
        self._users = {u["name"]: u for u in users}
        self._synced_at = time.time()

    # ---- 覆盖：先同步组织数据，再复用演示数据源的计算 ----
    def overview(self):
        self._sync()
        data = super().overview()
        # agent 在线数是真实的（目前为 0），历史趋势也不能沿用演示值
        data["daily_ops"] = [{**d, "online": 0} for d in data["daily_ops"]]
        return data

    def departments(self):
        self._sync()
        return super().departments()

    def members(self, dept=None, q=None):
        self._sync()
        return super().members(dept, q)

    def role_packs(self):
        self._sync()
        return super().role_packs()

    def role_pack(self, role_pack_id):
        self._sync()
        return super().role_pack(role_pack_id)

    def usage(self, days=30):
        self._sync()
        return super().usage(days)

    def assign_role_pack(self, member_id: str, role_pack_id: str) -> dict:
        self._sync()
        self._find(self.d["role_packs"], role_pack_id, "岗位包")
        if member_id not in self._users:
            raise NotFound(f"成员 {member_id} 不存在")
        uid = f"{self.org}/{member_id}"
        user = self._get("/api/get-user", id=uid)
        user["properties"] = {**(user.get("properties") or {}), ROLE_PACK_PROP: role_pack_id}
        body = self.http.post("/api/update-user", params={"id": uid}, json=user).json()
        if body.get("status") != "ok":
            raise RuntimeError(f"更新 Casdoor 用户失败：{body.get('msg')}")
        self._sync(force=True)
        return next(m for m in self.members() if m["id"] == member_id)
