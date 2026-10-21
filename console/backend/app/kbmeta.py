"""知识库本身的元数据（名称、部门、密级、是否开放外部、内容类型、负责人、复核周期）。

存在 kbs 表里；首次启动从 demo_seed.KNOWLEDGE_BASES 导入。`content.KB_REGISTRY` / `KB_BY_NAME` 是原地更新的同一个字典对象
（权限、检索、同步都直接读它），这里负责按数据库刷新它：每个进程最多每 30 秒读一次库，写操作后立刻刷新。
没配置数据库（单元测试、演示模式）时保持内置的种子数据。
"""

from __future__ import annotations

import logging
import math
import secrets
import time
from datetime import datetime, timedelta

from . import db, demo_seed
from .config import settings
from .content import KB_BY_NAME, KB_REGISTRY

log = logging.getLogger("hub.kbmeta")

CATEGORIES = ("制度", "产品", "品牌", "案例素材", "话术", "合规", "其他")
CLASSIFICATIONS = ("公开", "内部", "机密")
DEFAULT_REVIEW_DAYS = 90
TTL = 30.0
_SEED_CATEGORY = {"kb-brand": "品牌", "kb-product": "产品", "kb-banned": "合规", "kb-xhs-hits": "案例素材", "kb-competitor": "案例素材",
                  "kb-design-spec": "品牌", "kb-sales-policy": "制度", "kb-cs-faq": "话术", "kb-finance": "制度", "kb-hr": "制度", "kb-company": "制度"}
_state = {"at": 0.0}


class KbMetaError(ValueError):
    """参数不合法，消息可以直接给用户看。"""


def seed_if_empty() -> int:
    with db.connect() as conn:
        if conn.execute("SELECT count(*) AS n FROM kbs").fetchone()["n"]:
            return 0
        for kid, name, dept, level, source, external in demo_seed.KNOWLEDGE_BASES:
            conn.execute("INSERT INTO kbs (id, name, dept_id, classification, external_access, source, category, last_reviewed_at) "
                         "VALUES (%s, %s, %s, %s, %s, %s, %s, now())", (kid, name, dept, level, external, source, _SEED_CATEGORY.get(kid, "其他")))
    return len(demo_seed.KNOWLEDGE_BASES)


def _entry(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "dept": r["dept_id"], "classification": r["classification"], "source": r["source"],
            "external_access": r["external_access"], "category": r["category"], "owner": r["owner"],
            "review_every_days": r["review_every_days"], "description": r["description"],
            "last_reviewed_at": r["last_reviewed_at"].isoformat() if r["last_reviewed_at"] else None}


def refresh(force: bool = False) -> None:
    """按数据库刷新 KB_REGISTRY / KB_BY_NAME（原地更新，先加再删，读的线程不会看到缺项）。"""
    if not settings.database_url or (not force and time.time() - _state["at"] < TTL):
        return
    try:
        seed_if_empty()
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM kbs ORDER BY created_at, id").fetchall()
    except Exception as e:  # noqa: BLE001 库暂时不可用：保持现有内容
        log.warning("读取知识库配置失败，沿用内存里的：%s", e)
        return
    new = {r["id"]: _entry(r) for r in rows}
    KB_REGISTRY.update(new)
    for gone in [k for k in KB_REGISTRY if k not in new]:
        KB_REGISTRY.pop(gone, None)
    names = {v["name"]: k for k, v in KB_REGISTRY.items()}
    KB_BY_NAME.update(names)
    for gone in [k for k in KB_BY_NAME if k not in names]:
        KB_BY_NAME.pop(gone, None)
    _state["at"] = time.time()


def is_overdue(kb: dict, now: datetime | None = None) -> bool:
    days = kb.get("review_every_days") or 0
    if not days:
        return False
    last = kb.get("last_reviewed_at")
    if not last:
        return True
    return (now or datetime.now().astimezone()) - datetime.fromisoformat(last) > timedelta(days=days)


def due_in_days(kb: dict, now: datetime | None = None) -> int | None:
    """距离下次复核还有几天（负数 = 已逾期几天）；不需要复核返回 None。"""
    days = kb.get("review_every_days") or 0
    if not days:
        return None
    last = kb.get("last_reviewed_at")
    if not last:
        return -1
    left = datetime.fromisoformat(last) + timedelta(days=days) - (now or datetime.now().astimezone())
    return left.days if left.total_seconds() >= 0 else -math.ceil((-left).total_seconds() / 86400)


def overdue(now: datetime | None = None) -> list[dict]:
    return [k for k in KB_REGISTRY.values() if is_overdue(k, now)]


def _clean(fields: dict, valid_depts: set[str] | None) -> dict:
    out = {}
    if "name" in fields:
        name = str(fields["name"] or "").strip()
        if not name or len(name) > 30:
            raise KbMetaError("知识库名称 1–30 个字。")
        if any(k["name"] == name and k["id"] != fields.get("_id") for k in KB_REGISTRY.values()):
            raise KbMetaError(f"知识库「{name}」已经存在。")
        out["name"] = name
    if "dept" in fields:
        if fields["dept"] != "all" and valid_depts is not None and fields["dept"] not in valid_depts:
            raise KbMetaError("部门不存在。")
        out["dept_id"] = fields["dept"]
    if "classification" in fields:
        if fields["classification"] not in CLASSIFICATIONS:
            raise KbMetaError(f"密级只能是：{'、'.join(CLASSIFICATIONS)}。")
        out["classification"] = fields["classification"]
    if "external_access" in fields:
        out["external_access"] = bool(fields["external_access"])
    if "category" in fields:
        if fields["category"] not in CATEGORIES:
            raise KbMetaError(f"内容类型只能是：{'、'.join(CATEGORIES)}。")
        out["category"] = fields["category"]
    if "owner" in fields:
        out["owner"] = str(fields["owner"] or "").strip()
    if "review_every_days" in fields:
        try:
            days = int(fields["review_every_days"])
        except (TypeError, ValueError):
            raise KbMetaError("复核周期要是整数天数（0 = 不需要复核）。") from None
        if not 0 <= days <= 3650:
            raise KbMetaError("复核周期要在 0–3650 天之间（0 = 不需要复核）。")
        out["review_every_days"] = days
    if "description" in fields:
        out["description"] = str(fields["description"] or "").strip()[:200]
    return out


def create(fields: dict, valid_depts: set[str] | None = None) -> dict:
    for need in ("name", "dept", "classification"):
        if need not in fields:
            raise KbMetaError("名称、部门、密级必填。")
    data = _clean({"category": "其他", "review_every_days": DEFAULT_REVIEW_DAYS, "external_access": False, **fields}, valid_depts)
    if data["classification"] == "机密" and data["external_access"]:
        raise KbMetaError("机密知识库不能开放给外部智能体。")
    kb_id = f"kb-{secrets.token_hex(4)}"
    cols = ["id", "source", *data]
    with db.connect() as conn:
        conn.execute(f"INSERT INTO kbs ({', '.join(cols)}, last_reviewed_at) VALUES ({', '.join(['%s'] * len(cols))}, now())", [kb_id, "控制台", *data.values()])
    refresh(force=True)
    return KB_REGISTRY[kb_id]


def update(kb_id: str, fields: dict, valid_depts: set[str] | None = None) -> dict:
    refresh()
    if kb_id not in KB_REGISTRY:
        raise KbMetaError("知识库不存在。")
    data = _clean({**fields, "_id": kb_id}, valid_depts)
    cur = KB_REGISTRY[kb_id]
    if data.get("classification", cur["classification"]) == "机密" and data.get("external_access", cur["external_access"]):
        raise KbMetaError("机密知识库不能开放给外部智能体。")
    if data:
        sets = ", ".join(f"{k} = %s" for k in data)
        with db.connect() as conn:
            conn.execute(f"UPDATE kbs SET {sets}, updated_at = now() WHERE id = %s", [*data.values(), kb_id])
        refresh(force=True)
    return KB_REGISTRY[kb_id]


def mark_reviewed(kb_id: str) -> dict:
    refresh()
    if kb_id not in KB_REGISTRY:
        raise KbMetaError("知识库不存在。")
    with db.connect() as conn:
        conn.execute("UPDATE kbs SET last_reviewed_at = now(), updated_at = now() WHERE id = %s", (kb_id,))
    refresh(force=True)
    return KB_REGISTRY[kb_id]
