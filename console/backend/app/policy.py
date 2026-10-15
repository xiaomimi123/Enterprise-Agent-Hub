"""权限判断：一个员工能用哪些技能、查哪些知识库，全部由他的岗位包决定。

这是「权限在中枢强制执行」的核心：MCP Server 每次调用都走这里，与提示词怎么写无关。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import db
from .content import KB_REGISTRY

FALLBACK_ROLE_PACK = "rp-general"
OFFICIAL = "官方 agent"
EXTERNAL = "外部智能体"

# 部门（Casdoor 分组名）→ 默认岗位包。真实客户的分组名不同，按实际情况调整
DEFAULT_ROLE_PACKS = {
    "ops": "rp-xhs-ops", "design": "rp-designer", "video": "rp-video", "sales": "rp-sales",
    "cs": "rp-cs", "finance": "rp-finance", "hr": "rp-hr", "tech": "rp-general", "ceo": "rp-general",
}


@dataclass
class Principal:
    """一次 MCP 调用背后的人：谁、哪个部门、通过什么入口、拿着哪个岗位包。"""
    org: str
    user_name: str
    display_name: str
    dept: str
    channel: str
    pack: dict = field(default_factory=dict)

    @property
    def is_external(self) -> bool:
        return self.channel != OFFICIAL


def dept_from_groups(groups: list[str] | None) -> str:
    for g in groups or []:
        return g.split("/", 1)[-1]
    return ""


def resolve_pack(org: str, user_name: str, dept: str) -> dict:
    packs = {p["id"]: p for p in db.role_packs()}
    pack_id = db.assignments(org).get(user_name) or DEFAULT_ROLE_PACKS.get(dept) or FALLBACK_ROLE_PACK
    return packs.get(pack_id) or packs[FALLBACK_ROLE_PACK]


def allowed_kbs(p: Principal) -> list[str]:
    """这个人在当前入口下能检索的知识库。外部智能体只能读岗位包允许、且知识库本身开放给外部的。"""
    kbs = [k for k in p.pack.get("knowledge_bases", []) if k in KB_REGISTRY]
    if p.is_external:
        if p.pack.get("external_access") != "只读":
            return []
        kbs = [k for k in kbs if KB_REGISTRY[k]["external_access"]]
    return kbs


def can_use_tool(p: Principal, tool: str) -> bool:
    return tool in p.pack.get("tools", [])


def explain_kb_denial(p: Principal, kb_id: str) -> str:
    kb = KB_REGISTRY[kb_id]
    if kb_id not in p.pack.get("knowledge_bases", []):
        return f"岗位包「{p.pack['name']}」没有「{kb['name']}」的检索权限"
    if p.is_external and p.pack.get("external_access") != "只读":
        return f"岗位包「{p.pack['name']}」不允许外部智能体接入"
    return f"「{kb['name']}」未开放给外部智能体"
